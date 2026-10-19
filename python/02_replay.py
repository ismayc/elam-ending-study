"""Tier 1, literal replay: walk each game's real play-by-play under the Elam
rule and record who reaches the target first.

Rule (docs/design.md): the trigger is the first dead ball with strictly under
4:00 left in Q4; the target is the leading score at that moment plus 8 (a tie
gives the tied score plus 8). From the trigger on, the first team whose score
reaches the target wins. Overtime events count: the real game kept going, so
the replay keeps reading it. A game where neither team reaches the target
before the real game ends is "unresolved", never assigned a winner.

This is a bound, not a counterfactual: real teams played to the clock, not to
a target, so the replay keeps every clock-driven behavior (fouling to stop the
clock, holding for the last shot) that Elam would remove.

Reads data/events.parquet and output/games.csv (01_import.py). Writes
output/replay_games.csv (one row per game) and output/replay_summary.csv (one
row per league, season, and season type, plus pooled rows). --check rebuilds
in memory and fails if either file differs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "events.parquet"
GAMES = ROOT / "output" / "games.csv"
REPLAY = ROOT / "output" / "replay_games.csv"
SUMMARY = ROOT / "output" / "replay_summary.csv"

TRIGGER_SECS = 240.0   # strictly under 4:00 of Q4
TARGET_MARGIN = 8      # TBT rule


def triggers(events: pl.DataFrame) -> pl.DataFrame:
    """One row per game: the trigger event. A game with no dead ball under
    4:00 of Q4 (none expected; counted) triggers at its last Q4 event."""
    q4 = events.filter(pl.col("period") == 4)
    first_dead = (q4.filter(pl.col("dead_ball") & (pl.col("secs_left") < TRIGGER_SECS))
                  .group_by("gameId").agg(pl.all().sort_by("seq").first())
                  .with_columns(trigger_kind=pl.lit("dead ball")))
    fallback = (q4.filter(~pl.col("gameId").is_in(first_dead["gameId"].implode()))
                .group_by("gameId").agg(pl.all().sort_by("seq").last())
                .with_columns(trigger_kind=pl.lit("end of regulation")))
    cols = ["gameId", "seq", "period", "secs_left", "actionType", "score_h", "score_a",
            "trigger_kind"]
    return (pl.concat([first_dead.select(cols), fallback.select(cols)])
            .rename({"seq": "trigger_seq", "secs_left": "trigger_secs_left",
                     "actionType": "trigger_action", "score_h": "trigger_h",
                     "score_a": "trigger_a"})
            .drop("period"))


def replay(events: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    trig = triggers(events).with_columns(
        target=pl.max_horizontal("trigger_h", "trigger_a") + TARGET_MARGIN)
    after = (events.join(trig.select("gameId", "trigger_seq", "target"), on="gameId",
                         how="inner", validate="m:1")
             .filter(pl.col("seq") > pl.col("trigger_seq"))
             .filter((pl.col("score_h") >= pl.col("target"))
                     | (pl.col("score_a") >= pl.col("target")))
             .group_by("gameId").agg(pl.all().sort_by("seq").first())
             .select("gameId",
                     reach_seq="seq", reach_period="period", reach_secs_left="secs_left",
                     elam_winner=pl.when(pl.col("score_h") >= pl.col("target"))
                                   .then(pl.lit("home")).otherwise(pl.lit("away")),
                     reach_h="score_h", reach_a="score_a"))
    out = (games.select("gameId", "league", "season", "season_type", "final_home",
                        "final_away", "periods")
           .join(trig, on="gameId", how="left", validate="1:1")
           .join(after, on="gameId", how="left", validate="1:1")
           .with_columns(
               actual_winner=pl.when(pl.col("final_home") > pl.col("final_away"))
                               .then(pl.lit("home")).otherwise(pl.lit("away")),
               elam_winner=pl.col("elam_winner").fill_null(pl.lit("unresolved")),
               trigger_margin=(pl.col("trigger_h") - pl.col("trigger_a")).abs(),
               trigger_leader=pl.when(pl.col("trigger_h") > pl.col("trigger_a"))
                                .then(pl.lit("home"))
                                .when(pl.col("trigger_h") < pl.col("trigger_a"))
                                .then(pl.lit("away")).otherwise(pl.lit("tied")),
               overtime=pl.col("periods") > 4,
           )
           .with_columns(
               flipped=(pl.col("elam_winner") != "unresolved")
                       & (pl.col("elam_winner") != pl.col("actual_winner")),
               # Regulation seconds left when the target was reached; overtime
               # reaches count as 0 (the replay needed time the clock never had).
               reach_in_regulation=(pl.col("reach_period") == 4),
           )
           .sort("gameId"))
    return out


def summarize(rep: pl.DataFrame) -> pl.DataFrame:
    def agg(frame: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
        return (frame.group_by(keys).agg(
                    games=pl.len(),
                    trigger_dead_ball=(pl.col("trigger_kind") == "dead ball").sum(),
                    unresolved=(pl.col("elam_winner") == "unresolved").sum(),
                    flipped=pl.col("flipped").sum(),
                    overtime_games=pl.col("overtime").sum(),
                    overtime_resolved=(pl.col("overtime")
                                       & (pl.col("elam_winner") != "unresolved")).sum(),
                    overtime_flipped=(pl.col("overtime") & pl.col("flipped")).sum(),
                    leader_wins_actual=((pl.col("trigger_leader") == pl.col("actual_winner"))).sum(),
                    leader_wins_elam=((pl.col("trigger_leader") == pl.col("elam_winner"))).sum(),
                    tied_at_trigger=(pl.col("trigger_leader") == "tied").sum(),
                    reached_in_ot=(pl.col("reach_period") > 4).sum(),
                )
                .with_columns(flip_rate=pl.col("flipped") / pl.col("games"),
                              unresolved_rate=pl.col("unresolved") / pl.col("games")))
    by_season = agg(rep, ["league", "season", "season_type"])
    by_league = agg(rep, ["league", "season_type"]).with_columns(season=pl.lit("pooled"))
    by_league_all = (agg(rep, ["league"])
                     .with_columns(season=pl.lit("pooled"), season_type=pl.lit("all")))
    cols = by_season.columns
    return (pl.concat([by_season, by_league.select(cols), by_league_all.select(cols)])
            .sort("league", "season", "season_type"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="rebuild in memory and compare with the committed outputs")
    args = ap.parse_args()

    events = pl.read_parquet(EVENTS)
    games = pl.read_csv(GAMES, schema_overrides={"gameId": pl.Utf8})
    rep = replay(events, games)
    summ = summarize(rep)

    problems = []
    if rep.height != games.height:
        problems.append(f"replay has {rep.height} games, games.csv has {games.height}")
    if rep["trigger_seq"].null_count():
        problems.append(f"{rep['trigger_seq'].null_count()} games have no trigger")
    # Reaching the target needs at least 8 points after the trigger, so the
    # reach must come after the trigger and the winner's score must be the
    # target or (on a three) at most two over it.
    over = rep.filter(pl.col("elam_winner") != "unresolved").with_columns(
        w=pl.when(pl.col("elam_winner") == "home").then(pl.col("reach_h"))
            .otherwise(pl.col("reach_a")))
    bad = over.filter((pl.col("w") < pl.col("target")) | (pl.col("w") > pl.col("target") + 2))
    if bad.height:
        problems.append(f"{bad.height} games reach the target with an impossible score")

    with pl.Config(tbl_rows=40, tbl_cols=20, tbl_width_chars=220):
        print(summ.select("league", "season", "season_type", "games", "trigger_dead_ball",
                          "flipped", "flip_rate", "unresolved", "overtime_games",
                          "overtime_flipped", "reached_in_ot"))
    for p in problems:
        print("PROBLEM", p)

    if args.check:
        for path, fresh in [(REPLAY, rep), (SUMMARY, summ)]:
            if not path.exists():
                problems.append(f"{path.name} missing")
                continue
            old = pl.read_csv(path, schema_overrides={"gameId": pl.Utf8} if path == REPLAY else None)
            fresh_rt = pl.read_csv(fresh.write_csv().encode(),
                                   schema_overrides={"gameId": pl.Utf8} if path == REPLAY else None)
            if not old.equals(fresh_rt):
                problems.append(f"{path.name} differs from a fresh build")
        print("02_replay check:", "FAILED" if problems else "PASSED",
              f"({rep.height:,} games, {len(problems)} problems)")
        return 1 if problems else 0

    rep.write_csv(REPLAY)
    summ.write_csv(SUMMARY)
    print(f"wrote {REPLAY.relative_to(ROOT)} and {SUMMARY.relative_to(ROOT)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
