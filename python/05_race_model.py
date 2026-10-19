"""Tier 2, race to target: the exact probability that each team reaches the
Elam target first, from the real trigger state of every game.

Model. Possessions alternate. Each possession scores k = 0, 1, 2, 3, or 4+
points (counted as 4) with clock-neutral probabilities from
04_possessions.py. The state is (points home still needs, points away still
needs, team with the ball). With x = P(home wins | home has the ball) and
y = P(home wins | away has the ball) at one state, a scoreless possession
passes the ball and leaves the needs unchanged, so

    x = pH0 * y + C,   C = sum over k >= 1 of pH(k) * (1 if k >= home need else y')
    y = pA0 * x + B,   B = sum over k >= 1 of pA(k) * (0 if k >= away need else x')

where y' and x' are states with smaller needs, already solved. Then
x = (pH0 * B + C) / (1 - pH0 * pA0) and y = pA0 * x + B: exact, no
simulation, so the R implementation (R/05_race_model.R) can match it to
1e-9.

Two versions of the scoring distributions:
- league: both teams use their league-season's distribution;
- team: a possession by team T against defense D uses the average of T's
  offensive and D's defensive distributions (regular season, same season).

Who has the ball at the trigger: the team of the first shot, non-technical
free throw, or turnover after it.

Calibration: the same model, applied to real races inside games (the first
dead ball under 6:00 of Q2 and of Q3 in every regular-season game, target
leader + 8), against who actually got there first. Those races are played
without regard to the clock, which is the point.

Writes output/race_games.csv (one row per game), output/race_summary.csv,
output/race_calibration.csv, and output/race_by_margin.csv. --check rebuilds in memory and compares.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "events.parquet"
GAMES = ROOT / "output" / "games.csv"
REPLAY = ROOT / "output" / "replay_games.csv"
DIST = ROOT / "output" / "ppp_distributions.csv"
RACE = ROOT / "output" / "race_games.csv"
SUMMARY = ROOT / "output" / "race_summary.csv"
CALIB = ROOT / "output" / "race_calibration.csv"
MARGIN = ROOT / "output" / "race_by_margin.csv"
K = 5  # k = 0..4
TARGET_MARGIN = 8
CALIB_SECS = 360.0
BINS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]


def race(n_home: int, n_away: int, home_ball: bool, ph: list[float], pa: list[float],
         memo: dict) -> float:
    """P(home reaches its target first). ph, pa: P(k points) for a home and
    an away possession, k = 0..4. Solved bottom-up by total need so every
    smaller state exists before it is read."""
    key = (n_home, n_away)
    if key not in memo:
        for total in range(2, n_home + n_away + 1):
            for h in range(max(1, total - n_away), min(n_home, total - 1) + 1):
                a = total - h
                if (h, a) in memo:
                    continue
                c = sum(ph[k] * (1.0 if k >= h else memo[(h - k, a)][1]) for k in range(1, K))
                b = sum(pa[k] * (0.0 if k >= a else memo[(h, a - k)][0]) for k in range(1, K))
                x = (ph[0] * b + c) / (1.0 - ph[0] * pa[0])
                y = pa[0] * x + b
                memo[(h, a)] = (x, y)
    x, y = memo[key]
    return x if home_ball else y


def ball_after(events: pl.DataFrame, starts: pl.DataFrame) -> pl.DataFrame:
    """starts: gameId, start_seq. Returns gameId, start_seq, ball ('h' or 'v'):
    the side of the first shot, non-technical free throw, or turnover after
    start_seq."""
    offensive = (pl.col("actionType").is_in(["Made Shot", "Missed Shot", "Turnover"])
                 | ((pl.col("actionType") == "Free Throw")
                    & ~pl.col("description").str.to_lowercase().str.contains("technical")))
    cand = events.filter(offensive & pl.col("location").is_in(["h", "v"])).select(
        "gameId", "seq", "location")
    return (starts.join(cand, on="gameId", how="inner")
            .filter(pl.col("seq") > pl.col("start_seq"))
            .group_by("gameId", "start_seq").agg(ball=pl.col("location").sort_by("seq").first()))


def distributions(dist: pl.DataFrame) -> tuple[dict, dict, dict]:
    probs = lambda r: [r[f"p{k}"] for k in range(K)]  # noqa: E731
    league = {(r["league"], r["season"]): probs(r)
              for r in dist.filter(pl.col("scope") == "league").iter_rows(named=True)}
    off = {(r["league"], r["season"], r["team_id"]): probs(r)
           for r in dist.filter(pl.col("scope") == "offense").iter_rows(named=True)}
    dfn = {(r["league"], r["season"], r["team_id"]): probs(r)
           for r in dist.filter(pl.col("scope") == "defense").iter_rows(named=True)}
    return league, off, dfn


def solve(states: pl.DataFrame, dist: pl.DataFrame) -> pl.DataFrame:
    """states: gameId, league, season, home_team_id, away_team_id, score_h,
    score_a, ball. Adds target, p_home_league, p_home_team."""
    league, off, dfn = distributions(dist)
    mean = lambda u, v: [(a + b) / 2 for a, b in zip(u, v)]  # noqa: E731
    memos: dict = {}
    rows = []
    for r in states.iter_rows(named=True):
        target = max(r["score_h"], r["score_a"]) + TARGET_MARGIN
        nh, na = target - r["score_h"], target - r["score_a"]
        home_ball = r["ball"] == "h"
        lg = league[(r["league"], r["season"])]
        p_league = race(nh, na, home_ball, lg, lg, memos.setdefault(("L", r["league"], r["season"]), {}))
        key_h = (r["league"], r["season"], r["home_team_id"])
        key_a = (r["league"], r["season"], r["away_team_id"])
        if key_h in off and key_a in off:
            ph, pa = mean(off[key_h], dfn[key_a]), mean(off[key_a], dfn[key_h])
            p_team = race(nh, na, home_ball, ph, pa,
                          memos.setdefault(("T", r["league"], r["season"],
                                            r["home_team_id"], r["away_team_id"]), {}))
        else:
            p_team = None
        rows.append({**r, "target": target, "p_home_league": p_league, "p_home_team": p_team})
    return pl.DataFrame(rows, schema_overrides={"p_home_team": pl.Float64})


def game_races(events: pl.DataFrame, games: pl.DataFrame, replay: pl.DataFrame,
               dist: pl.DataFrame) -> pl.DataFrame:
    trig = replay.select("gameId", start_seq="trigger_seq", score_h="trigger_h",
                         score_a="trigger_a")
    ball = ball_after(events, trig)
    states = (trig.join(ball, on=["gameId", "start_seq"], how="left", validate="1:1")
              .join(games.select("gameId", "league", "season", "season_type",
                                 "home_team_id", "away_team_id"), on="gameId", validate="1:1")
              .with_columns(pl.col("ball").fill_null("h")))
    solved = solve(states, dist)
    rep = replay.select("gameId", "actual_winner", "elam_winner", "trigger_margin",
                        "trigger_leader", "flipped")
    return (solved.join(rep, on="gameId", validate="1:1").with_columns(
        p_actual_league=pl.when(pl.col("actual_winner") == "home")
                          .then(pl.col("p_home_league")).otherwise(1 - pl.col("p_home_league")),
        p_actual_team=pl.when(pl.col("actual_winner") == "home")
                        .then(pl.col("p_home_team")).otherwise(1 - pl.col("p_home_team")),
        p_leader_league=pl.when(pl.col("trigger_leader") == "home").then(pl.col("p_home_league"))
                          .when(pl.col("trigger_leader") == "away").then(1 - pl.col("p_home_league"))
                          .otherwise(None),
    ).sort("gameId"))


def summarize(rg: pl.DataFrame) -> pl.DataFrame:
    """Expected flips = sum over games of P(the real loser reaches the target
    first). Leader wins: the real (clock) rate and the model's expected rate,
    for games with a leader at the trigger."""
    def agg(frame, keys):
        led = pl.col("trigger_leader") != "tied"
        return frame.group_by(keys).agg(
            games=pl.len(),
            expected_flips_league=(1 - pl.col("p_actual_league")).sum(),
            expected_flips_team=(1 - pl.col("p_actual_team")).sum(),
            led_games=led.sum(),
            leader_won_clock=(led & (pl.col("trigger_leader") == pl.col("actual_winner"))).sum(),
            leader_wins_elam_league=pl.col("p_leader_league").sum(),
        ).with_columns(
            expected_flip_rate_league=pl.col("expected_flips_league") / pl.col("games"),
            expected_flip_rate_team=pl.col("expected_flips_team") / pl.col("games"),
            leader_win_rate_clock=pl.col("leader_won_clock") / pl.col("led_games"),
            leader_win_rate_elam_league=pl.col("leader_wins_elam_league") / pl.col("led_games"))
    s = agg(rg, ["league", "season", "season_type"])
    p = agg(rg, ["league", "season_type"]).with_columns(season=pl.lit("pooled"))
    a = agg(rg, ["league"]).with_columns(season=pl.lit("pooled"), season_type=pl.lit("all"))
    return pl.concat([s, p.select(s.columns), a.select(s.columns)]).sort(
        "league", "season", "season_type")


MARGIN_BREAKS = [1, 2, 3, 4, 5, 6, 8, 10, 15]


def by_margin(rg: pl.DataFrame) -> pl.DataFrame:
    """Leader's win rate under the clock (real games, with a 95% Wilson
    interval) against the model's mean P(leader reaches the target first),
    by margin at the trigger, per league. Tied triggers are excluded."""
    labels = ["1", "2", "3", "4", "5", "6", "7-8", "9-10", "11-15", "16+"]
    d = rg.filter(pl.col("trigger_leader") != "tied").with_columns(
        margin=pl.col("trigger_margin").cut(MARGIN_BREAKS, labels=labels).cast(pl.Utf8),
        won=(pl.col("trigger_leader") == pl.col("actual_winner")).cast(pl.Float64))
    t = d.group_by("league", "margin").agg(
        games=pl.len(), clock=pl.col("won").mean(),
        elam_league=pl.col("p_leader_league").mean(),
        elam_team=pl.when(pl.col("trigger_leader") == "home").then(pl.col("p_home_team"))
                    .otherwise(1 - pl.col("p_home_team")).mean())
    # Wilson 95% interval: deterministic like the rest (R mirrors it), and it
    # stays inside [0, 1] where the normal approximation ran past 1.
    z, n, p = 1.96, pl.col("games"), pl.col("clock")
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * (p * (1 - p) / n + z * z / (4 * n * n)).sqrt() / (1 + z * z / n)
    order = {lab: i for i, lab in enumerate(labels)}
    return (t.with_columns(clock_lo=centre - half, clock_hi=centre + half,
                           elam_minus_clock=pl.col("elam_league") - pl.col("clock"),
                           o=pl.col("margin").replace_strict(order, return_dtype=pl.Int32))
            .sort("league", "o").drop("o"))


def calibration_races(events: pl.DataFrame, games: pl.DataFrame,
                      dist: pl.DataFrame) -> pl.DataFrame:
    """Mid-game races: first dead ball under 6:00 of Q2 and of Q3, regular
    season; outcome = who first reaches leader + 8 in the real game."""
    reg = games.filter(pl.col("season_type") == "regular").select(
        "gameId", "league", "season", "home_team_id", "away_team_id")
    ev = events.filter(pl.col("gameId").is_in(reg["gameId"].implode()))
    start = (ev.filter(pl.col("period").is_in([2, 3]) & pl.col("dead_ball")
                       & (pl.col("secs_left") < CALIB_SECS))
             .group_by("gameId", "period").agg(pl.all().sort_by("seq").first())
             .select("gameId", race_period="period", start_seq="seq",
                     score_h="score_h", score_a="score_a"))
    ball = ball_after(ev, start.select("gameId", "start_seq"))
    states = (start.join(ball, on=["gameId", "start_seq"], how="left", validate="1:1")
              .join(reg, on="gameId", validate="m:1")
              .filter(pl.col("ball").is_not_null()))
    solved = solve(states, dist)
    outcome = (ev.join(solved.select("gameId", "race_period", "start_seq", "target"),
                       on="gameId", how="inner")
               .filter((pl.col("seq") > pl.col("start_seq"))
                       & ((pl.col("score_h") >= pl.col("target"))
                          | (pl.col("score_a") >= pl.col("target"))))
               .group_by("gameId", "race_period").agg(
                   home_first=(pl.col("score_h") >= pl.col("target")).sort_by("seq").first()))
    return (solved.join(outcome, on=["gameId", "race_period"], how="left", validate="1:1")
            .filter(pl.col("home_first").is_not_null())
            .with_columns(home_first=pl.col("home_first").cast(pl.Int8))
            .sort("gameId", "race_period"))


def calibration_table(cr: pl.DataFrame) -> pl.DataFrame:
    """Bins of the model's P(the team ahead, or with the ball if tied, gets
    there first), with the observed share; plus a Brier row per version."""
    rows = []
    for version in ["league", "team"]:
        p = pl.col(f"p_home_{version}")
        fav_home = p >= 0.5
        d = cr.filter(p.is_not_null()).with_columns(
            p_fav=pl.when(fav_home).then(p).otherwise(1 - p),
            fav_first=pl.when(fav_home).then(pl.col("home_first")).otherwise(1 - pl.col("home_first")))
        d = d.with_columns(bin=pl.col("p_fav").cut(BINS, left_closed=True).cast(pl.Utf8))
        t = (d.group_by("bin").agg(races=pl.len(), mean_predicted=pl.col("p_fav").mean(),
                                   observed=pl.col("fav_first").mean())
             .with_columns(version=pl.lit(version)))
        brier = ((d["p_fav"] - d["fav_first"]) ** 2).mean()
        base = d["fav_first"].mean()
        rows.append(t)
        rows.append(pl.DataFrame({"bin": ["all"], "races": [d.height],
                                  "mean_predicted": [d["p_fav"].mean()],
                                  "observed": [base], "version": [version]},
                                 schema_overrides={"races": pl.UInt32}))
        rows.append(pl.DataFrame({"bin": ["brier"], "races": [d.height],
                                  "mean_predicted": [brier],
                                  "observed": [((base - d["fav_first"]) ** 2).mean()],
                                  "version": [version]},
                                 schema_overrides={"races": pl.UInt32}))
    return pl.concat(rows).select("version", "bin", "races", "mean_predicted", "observed").sort(
        "version", "bin")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    events = pl.read_parquet(EVENTS)
    ids = {"gameId": pl.Utf8, "home_team_id": pl.Utf8, "away_team_id": pl.Utf8}
    games = pl.read_csv(GAMES, schema_overrides=ids)
    replay = pl.read_csv(REPLAY, schema_overrides={"gameId": pl.Utf8})
    dist = pl.read_csv(DIST, schema_overrides={"team_id": pl.Utf8})

    rg = game_races(events, games, replay, dist)
    summ = summarize(rg)
    marg = by_margin(rg)
    cal = calibration_table(calibration_races(events, games, dist))
    problems = []
    if rg.height != games.height:
        problems.append(f"race_games has {rg.height} games, games.csv {games.height}")
    if rg["p_home_league"].null_count() or not rg["p_home_league"].is_between(0, 1).all():
        problems.append("p_home_league missing or outside [0, 1]")

    with pl.Config(tbl_rows=40, tbl_cols=20, tbl_width_chars=230):
        print(summ.select("league", "season", "season_type", "games",
                          "expected_flips_league", "expected_flips_team",
                          "leader_win_rate_clock", "leader_win_rate_elam_league"))
        print(cal)
        print(marg)
    for p in problems:
        print("PROBLEM", p)

    outs = [(RACE, rg, {"gameId": pl.Utf8, **{k: pl.Utf8 for k in ids}}),
            (SUMMARY, summ, None), (CALIB, cal, None), (MARGIN, marg, None)]
    if args.check:
        problems += [why for path, fresh, so in outs
                     if (why := checks.matches(path, fresh, so))]
        print("05_race_model check:", "FAILED" if problems else "PASSED",
              f"({rg.height:,} games, {len(problems)} problems)")
        return 1 if problems else 0
    for path, fresh, _ in outs:
        fresh.write_csv(path)
    print("wrote", ", ".join(p.name for p, _, _ in outs))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
