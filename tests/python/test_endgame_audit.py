"""06_endgame_audit per-game measures on a hand-built game."""
from __future__ import annotations

import polars as pl


def test_per_game_measures(audit, monkeypatch):
    # Home wins 103-101. Away leads 101-99 with 0:50 left; home ties on free
    # throws at 0:30, then its free throw at 0:10 (102-101) is the lead it
    # never loses: decided late, and the last score is a free throw. Away
    # commits a take foul while trailing.
    ev = pl.DataFrame([
        # seq, period, secs, type, subtype, loc, h, a
        (0, 3, 300.0, "Made Shot", "", "h", 96, 0),
        (1, 3, 200.0, "Free Throw", "", "v", 96, 98),
        (2, 4, 230.0, "Made Shot", "", "h", 99, 98),
        (3, 4, 50.0, "Made Shot", "", "v", 99, 101),
        (4, 4, 30.0, "Free Throw", "", "h", 100, 101),
        (5, 4, 30.0, "Free Throw", "", "h", 101, 101),
        (6, 4, 10.0, "Foul", "Personal Take", "v", 101, 101),
        (7, 4, 10.0, "Free Throw", "", "h", 102, 101),
        (8, 4, 10.0, "Free Throw", "", "h", 103, 101),
    ], schema=["seq", "period", "secs_left", "actionType", "subType", "location",
               "score_h", "score_a"], orient="row").with_columns(gameId=pl.lit("0022599999"))
    games = pl.DataFrame([{"gameId": "0022599999", "league": "nba", "season": "2025-26",
                           "season_type": "regular", "periods": 4,
                           "final_home": 103, "final_away": 101}])
    monkeypatch.setattr(audit, "wall_clock", lambda ids: pl.DataFrame(
        {"gameId": ids, "real_secs_q4_last2": [600.0], "real_secs_q3_mid2": [300.0]}))
    r = audit.per_game(ev, games).row(0, named=True)
    # The take foul at 101-101 is by a team that is tied, not trailing.
    assert (r["take_fouls_last2"], r["take_fouls_trailing_last2"]) == (1, 0)
    # Endgame (last 4:00): 3 + 3 + four free throws = 10 points, 4 from FTs.
    assert (r["endgame_pts"], r["endgame_ft_pts"]) == (10, 4)
    assert r["last_score_ft"] is True and r["decided_late"] is True
    assert r["margin_at_2min"] == 1
