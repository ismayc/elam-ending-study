"""Running-score rules in 01_import.prepare, each pinned to the real case that
forced it (rows trimmed to the columns prepare reads)."""
from __future__ import annotations

import polars as pl

COLS = ["gameId", "actionNumber", "clock", "period", "teamId", "location",
        "actionType", "subType", "description", "shotResult", "isFieldGoal",
        "scoreHome", "scoreAway"]


def rows(*events):
    """events: (actionNumber, clock, actionType, location, scoreHome, scoreAway)."""
    return pl.DataFrame(
        [{"gameId": "0022300001", "actionNumber": str(n), "clock": c, "period": "4",
          "teamId": "1", "location": loc, "actionType": t, "subType": "",
          "description": "", "shotResult": "", "isFieldGoal": "0",
          "scoreHome": h, "scoreAway": a} for n, c, t, loc, h, a in events],
        schema={k: pl.Utf8 for k in COLS})


def scores(df):
    return list(zip(df["score_h"].to_list(), df["score_a"].to_list()))


def test_instant_replay_stamp_is_ignored(imp):
    # 0022300010: the replay row reads 53-44 after free throws made it 55-44.
    out = imp.prepare(rows(
        (1, "PT04M17.00S", "Free Throw", "h", "55", "44"),
        (2, "PT04M17.00S", "Instant Replay", "", "53", "44"),
        (3, "PT03M59.00S", "Made Shot", "v", "55", "46"),
    ))
    assert scores(out) == [(55, 0), (55, 0), (55, 46)]


def test_stamp_sets_only_the_scoring_team(imp):
    # 0022500527: Camara's (home) free throw is stamped 93-91; away was on 89.
    out = imp.prepare(rows(
        (1, "PT04M43.00S", "Made Shot", "v", "91", "89"),
        (2, "PT04M32.00S", "Free Throw", "h", "93", "91"),
    ))
    assert scores(out) == [(0, 89), (93, 89)]


def test_out_of_order_same_instant_free_throws(imp):
    # 0022300055: a technical free throw stamped 124 sorts after the and-one
    # free throw stamped 126 at the same clock reading; the score stays 126.
    out = imp.prepare(rows(
        (647, "PT03M54.00S", "Free Throw", "h", "126", "103"),
        (655, "PT03M54.00S", "Free Throw", "h", "124", "103"),
        (660, "PT03M34.00S", "Missed Shot", "v", "", ""),
    ))
    assert [h for h, _ in scores(out)] == [126, 126, 126]


def test_clock_order_beats_action_number(imp):
    # A late-inserted event (high actionNumber, earlier clock) sorts by clock.
    out = imp.prepare(rows(
        (900, "PT05M05.00S", "Made Shot", "h", "10", "0"),
        (100, "PT04M00.00S", "Made Shot", "h", "12", "0"),
    ))
    assert out["actionNumber"].to_list() == [900, 100]
    assert [h for h, _ in scores(out)] == [10, 12]


def test_game_meta(imp):
    df = pl.DataFrame({"g": ["0022500001", "0042300405", "1022600017", "1042400101"]})
    out = df.select(imp.game_meta(pl.col("g")))
    assert out.rows() == [("nba", "2025-26", "regular"), ("nba", "2023-24", "playoffs"),
                          ("wnba", "2026", "regular"), ("wnba", "2024", "playoffs")]
