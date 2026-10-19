"""Points per possession, the input to the tier 2 race model.

Possessions come from playbyplay-study's pbpstats builds (regular season,
all six league-seasons). Points are assigned from this study's events: a
possession owns the offense's points scored at clock readings strictly under
its start and at or above its end, so free throws at the instant a
possession ends belong to it, and a made basket at the instant the next one
starts belongs to the one it ended.

Clock-neutral possessions only, since Elam removes the clock: Q1 to Q3
possessions that start with more than 60 seconds left in the period (the
2-for-1 and last-shot windows are clock play), plus Q4 possessions that start
with more than 5:00 left. Playoff games have no possession builds; the model
uses each league-season's regular-season distribution for them.

Writes data/possessions.parquet (local) and output/ppp_distributions.csv:
one row per scope (league-season; team-season on offense; team-season on
defense) with the share of possessions scoring 0, 1, 2, 3, and 4 or more
points. --check rebuilds in memory and compares, and fails if possession
points miss more than 1% of the points scored in those windows.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POSS_DIR = ROOT.parent / "playbyplay-study" / "data" / "possessions"
EVENTS = ROOT / "data" / "events.parquet"
POSS_OUT = ROOT / "data" / "possessions.parquet"
DIST = ROOT / "output" / "ppp_distributions.csv"
MAX_K = 4  # 4 or more points in one possession pooled (and-one threes, flagrants)


def clock_neutral() -> pl.Expr:
    """Also drops each period's first possession: pbpstats' offense team is
    unreliable there. In NBA 2023-24, 37% of scoring rows inside a
    period-start possession belong to the listed defense, against 0.9%
    elsewhere (October 19, 2026), so those possessions would score the wrong
    team. They are about 2% of possessions."""
    period_start = pl.col("start_secs") == pl.col("start_secs").max().over("gameId", "period")
    return ((((pl.col("period") <= 3) & (pl.col("start_secs") > 60))
             | ((pl.col("period") == 4) & (pl.col("start_secs") > 300)))
            & ~period_start)


def load_possessions() -> pl.DataFrame:
    p = pl.read_parquet(POSS_DIR / "*.parquet")
    return p.select(
        gameId=pl.col("game_id").cast(pl.Utf8).str.zfill(10),
        period=pl.col("PERIOD").cast(pl.Int32),
        start_secs="start_secs", end_secs="end_secs",
        offense_team_id=pl.col("offense_team_id").cast(pl.Utf8),
    ).with_row_index("poss_id")


def team_points(events: pl.DataFrame) -> pl.DataFrame:
    """One row per scoring change: (game, period, secs_left, team, points)."""
    ev = events.select("gameId", "period", "secs_left", "seq", "score_h", "score_a",
                       "location", "teamId")
    ev = ev.with_columns(dh=pl.col("score_h").diff().over("gameId").fill_null(pl.col("score_h")),
                         da=pl.col("score_a").diff().over("gameId").fill_null(pl.col("score_a")))
    return ev.filter((pl.col("dh") > 0) | (pl.col("da") > 0)).with_columns(
        side=pl.when(pl.col("dh") > 0).then(pl.lit("h")).otherwise(pl.lit("v")),
        pts=pl.max_horizontal("dh", "da"))


def build(events: pl.DataFrame, games: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, list[str]]:
    poss = load_possessions()
    teams = games.select("gameId", "home_team_id", "away_team_id", "league", "season")
    poss = poss.join(teams, on="gameId", how="inner", validate="m:1").with_columns(
        off_side=pl.when(pl.col("offense_team_id") == pl.col("home_team_id"))
                   .then(pl.lit("h")).otherwise(pl.lit("v")),
        defense_team_id=pl.when(pl.col("offense_team_id") == pl.col("home_team_id"))
                          .then(pl.col("away_team_id")).otherwise(pl.col("home_team_id")))
    scores = team_points(events)
    # Each scoring change to the possession whose window holds it, offense only.
    joined = (poss.select("poss_id", "gameId", "period", "start_secs", "end_secs", "off_side")
              .join(scores.select("gameId", "period", "secs_left", "side", "pts"),
                    on=["gameId", "period"], how="inner")
              .filter((pl.col("secs_left") < pl.col("start_secs"))
                      & (pl.col("secs_left") >= pl.col("end_secs"))
                      & (pl.col("side") == pl.col("off_side")))
              .group_by("poss_id").agg(points=pl.col("pts").sum()))
    poss = poss.join(joined, on="poss_id", how="left", validate="1:1").with_columns(
        pl.col("points").fill_null(0), neutral=clock_neutral())

    problems = []
    # Coverage: points owned by possessions vs all points scored by either
    # team inside clock-neutral windows (start of each neutral possession to
    # its end), per league-season.
    windows = poss.filter("neutral").select("gameId", "period", "start_secs", "end_secs",
                                            "league", "season")
    scored = (windows.join(scores.select("gameId", "period", "secs_left", "pts"),
                           on=["gameId", "period"], how="inner")
              .filter((pl.col("secs_left") < pl.col("start_secs"))
                      & (pl.col("secs_left") >= pl.col("end_secs")))
              .group_by("league", "season").agg(all_pts=pl.col("pts").sum()))
    owned = (poss.filter("neutral").group_by("league", "season")
             .agg(owned_pts=pl.col("points").sum(), possessions=pl.len()))
    cov = owned.join(scored, on=["league", "season"]).with_columns(
        share=pl.col("owned_pts") / pl.col("all_pts")).sort("league", "season")
    print(cov)
    for r in cov.filter(pl.col("share") < 0.99).iter_rows(named=True):
        problems.append(f"possession points cover {r['share']:.4f} of points in "
                        f"{r['league']} {r['season']}")

    neutral = poss.filter("neutral").with_columns(k=pl.min_horizontal("points", MAX_K))

    def dist(keys: list[str], scope: str, team_col: str | None) -> pl.DataFrame:
        d = (neutral.group_by(keys).agg(
                 n=pl.len(), mean_points=pl.col("points").mean(),
                 **{f"p{k}": (pl.col("k") == k).mean() for k in range(MAX_K + 1)})
             .with_columns(scope=pl.lit(scope)))
        d = d.rename({team_col: "team_id"}) if team_col else d.with_columns(team_id=pl.lit(""))
        return d.select("scope", "league", "season", "team_id", "n", "mean_points",
                        *[f"p{k}" for k in range(MAX_K + 1)])

    out = pl.concat([
        dist(["league", "season"], "league", None),
        dist(["league", "season", "offense_team_id"], "offense", "offense_team_id"),
        dist(["league", "season", "defense_team_id"], "defense", "defense_team_id"),
    ]).sort("scope", "league", "season", "team_id")
    return poss, out, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    events = pl.read_parquet(EVENTS)
    games = pl.read_csv(ROOT / "output" / "games.csv",
                        schema_overrides={"gameId": pl.Utf8, "home_team_id": pl.Utf8,
                                          "away_team_id": pl.Utf8})
    poss, dist, problems = build(events, games)
    with pl.Config(tbl_rows=10, tbl_cols=12, tbl_width_chars=200):
        print(dist.filter(pl.col("scope") == "league"))
    for p in problems:
        print("PROBLEM", p)
    if args.check:
        if why := checks.matches(DIST, dist, {"team_id": pl.Utf8}):
            problems.append(why)
        print("04_possessions check:", "FAILED" if problems else "PASSED",
              f"({poss.height:,} possessions, {len(problems)} problems)")
        return 1 if problems else 0
    poss.write_parquet(POSS_OUT)
    dist.write_csv(DIST)
    print(f"wrote {POSS_OUT.relative_to(ROOT)} and {DIST.relative_to(ROOT)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
