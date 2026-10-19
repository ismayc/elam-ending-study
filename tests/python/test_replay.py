"""02_replay rules on hand-built games with known answers."""
from __future__ import annotations

import polars as pl


def game(gid, events, final):
    """events: (period, secs_left, actionType, dead_ball, score_h, score_a)."""
    ev = pl.DataFrame(
        [{"gameId": gid, "seq": i, "period": p, "secs_left": s, "actionType": t,
          "dead_ball": d, "score_h": h, "score_a": a}
         for i, (p, s, t, d, h, a) in enumerate(events)],
        schema_overrides={"period": pl.Int32, "score_h": pl.Int32, "score_a": pl.Int32})
    periods = max(e[0] for e in events)
    g = pl.DataFrame([{"gameId": gid, "league": "nba", "season": "2025-26",
                       "season_type": "regular", "final_home": final[0],
                       "final_away": final[1], "periods": periods}])
    return ev, g


def run(rep, *games):
    ev = pl.concat([e for e, _ in games])
    g = pl.concat([x for _, x in games])
    return {r["gameId"]: r for r in rep.replay(ev, g).iter_rows(named=True)}


def test_trigger_is_first_dead_ball_strictly_under_four_minutes(rep):
    ev = game("g1", [
        (4, 240.0, "Foul", True, 100, 95),      # exactly 4:00: not under
        (4, 230.0, "Made Shot", False, 102, 95),  # live ball: no trigger
        (4, 220.0, "Timeout", True, 102, 95),   # trigger: target 110
        (4, 100.0, "Made Shot", False, 110, 99),
    ], (110, 99))
    r = run(rep, ev)["g1"]
    assert (r["trigger_secs_left"], r["target"]) == (220.0, 110)
    assert (r["elam_winner"], r["flipped"]) == ("home", False)


def test_trailer_reaching_target_first_is_a_flip(rep):
    # Home leads 100-98 at the trigger (target 108); away gets to 108 first,
    # then home wins the real game.
    ev = game("g2", [
        (4, 200.0, "Foul", True, 100, 98),
        (4, 100.0, "Made Shot", False, 100, 108),
        (4, 1.0, "Made Shot", False, 112, 108),
    ], (112, 108))
    r = run(rep, ev)["g2"]
    assert (r["elam_winner"], r["actual_winner"], r["flipped"]) == ("away", "home", True)


def test_tie_at_trigger_and_reach_in_overtime(rep):
    ev = game("g3", [
        (4, 210.0, "Timeout", True, 90, 90),    # tied: target 98
        (4, 0.0, "period", False, 96, 96),
        (5, 200.0, "Made Shot", False, 96, 98),
        (5, 0.0, "period", False, 101, 99),
    ], (101, 99))
    r = run(rep, ev)["g3"]
    assert r["trigger_leader"] == "tied" and r["target"] == 98
    assert (r["elam_winner"], r["reach_period"], r["flipped"]) == ("away", 5, True)


def test_unresolved_when_nobody_reaches_target(rep):
    ev = game("g4", [
        (4, 150.0, "Foul", True, 120, 100),     # target 128
        (4, 0.0, "period", False, 127, 110),
    ], (127, 110))
    r = run(rep, ev)["g4"]
    assert (r["elam_winner"], r["flipped"]) == ("unresolved", False)


def test_no_dead_ball_falls_back_to_end_of_regulation(rep):
    ev = game("g5", [
        (4, 300.0, "Foul", True, 80, 60),       # before 4:00: does not count
        (4, 100.0, "Made Shot", False, 82, 60),
        (4, 0.0, "period", False, 82, 60),
    ], (82, 60))
    r = run(rep, ev)["g5"]
    assert (r["trigger_kind"], r["trigger_secs_left"]) == ("end of regulation", 0.0)
