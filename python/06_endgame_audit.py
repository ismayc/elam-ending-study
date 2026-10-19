"""Tier 3, the endgame audit: what the clock does to the end of real games,
measured directly. Every quantity here is factual; nothing is modeled.

Per game:
- overtime: the game went past regulation (Elam abolishes overtime);
- take fouls (V3 "Personal Take"; liveData descriptor "take") in the last
  2:00 of Q4 and in overtime, all and by the team trailing at the foul;
- points and free-throw points in the endgame (the last 4:00 of Q4 plus
  overtime, the stretch Elam replaces) and in Q1 to Q3;
- the kind of the game's last scoring play (field goal or free throw);
- decided late: the winner's final go-ahead score (the lead it never lost)
  came in the last 60 seconds of the final period;
- real (wall-clock) minutes that the last 2:00 of Q4 took, and that a
  neutral 2:00 (Q3 from 6:00 to 4:00) took, from liveData's timeActual,
  with the score margin at 2:00 of Q4 so close games (5 or fewer) can be
  split out.

Writes output/endgame_games.csv and output/endgame_summary.csv (per league,
season, and season type, plus pooled rows). --check rebuilds and compares.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "events.parquet"
GAMES = ROOT / "output" / "games.csv"
LIVE_REG = ROOT.parent / "playbyplay-study" / "data" / "pbpstats_live" / "pbp"
LIVE_PO = ROOT / "data" / "raw" / "live"
OUT_GAMES = ROOT / "output" / "endgame_games.csv"
OUT_SUMMARY = ROOT / "output" / "endgame_summary.csv"


def scoring_rows(events: pl.DataFrame) -> pl.DataFrame:
    ev = events.with_columns(
        dh=pl.col("score_h").diff().over("gameId").fill_null(pl.col("score_h")),
        da=pl.col("score_a").diff().over("gameId").fill_null(pl.col("score_a")))
    return ev.filter((pl.col("dh") > 0) | (pl.col("da") > 0)).with_columns(
        pts=pl.max_horizontal("dh", "da"),
        is_ft=pl.col("actionType") == "Free Throw")


WALL_MAX = 3600.0  # a 2:00 stretch longer than an hour is a feed fault or a delay


def wall_clock(game_ids: list[str]) -> pl.DataFrame:
    """Real seconds that two minutes of game clock took: Q4 from 2:00 to the
    period-end action, and Q3 from 6:00 to 4:00.

    The wall time at a clock reading c is the last action at or above c plus
    (its clock - c): the clock runs one second per real second while play is
    live, so this is exact when the clock was running and a slight undercount
    when it was stopped. Anchoring on the first action under c instead missed
    the play before it (0022300514's first action under 2:00 is at 1:23, and
    its last 2:00 came out at 107 real seconds). Durations under the game time
    or over WALL_MAX are feed faults (0022500232's timestamps give -11,265
    seconds) and are left empty."""
    def stamp(a: dict) -> float:
        return datetime.fromisoformat(a["timeActual"].replace("Z", "+00:00")).timestamp()

    def secs(a: dict) -> float:
        m, s = a["clock"][2:].rstrip("S").split("M")
        return int(m) * 60 + float(s)

    def wall_at(actions, period, c):
        before = [a for a in actions if a["period"] == period and secs(a) >= c]
        if not before:
            return None
        a = before[-1]
        return stamp(a) + (secs(a) - c)

    def span(start, end, game_secs):
        if start is None or end is None:
            return None
        # Stamps are tenths of a second and clocks hundredths, so the true
        # span has two decimals; rounding drops float noise in the epoch
        # seconds (about 1e-7), which R parses differently.
        d = round(end - start, 2)
        return d if game_secs <= d <= WALL_MAX else None

    rows = []
    for g in game_ids:
        path = (LIVE_REG / f"live_{g}.json") if g[2] == "2" else (LIVE_PO / f"{g}.json")
        q4 = q3 = None
        if path.exists():
            actions = json.loads(path.read_text())["game"]["actions"]
            end = next((a for a in actions if a["period"] == 4 and a["actionType"] == "period"
                        and a.get("subType") == "end"), None)
            q4 = span(wall_at(actions, 4, 120.0), stamp(end) if end else None, 120.0)
            q3 = span(wall_at(actions, 3, 360.0), wall_at(actions, 3, 240.0), 120.0)
        rows.append({"gameId": g, "real_secs_q4_last2": q4, "real_secs_q3_mid2": q3})
    return pl.DataFrame(rows, schema={"gameId": pl.Utf8, "real_secs_q4_last2": pl.Float64,
                                      "real_secs_q3_mid2": pl.Float64})


def per_game(events: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    last2 = (pl.col("period") > 4) | ((pl.col("period") == 4) & (pl.col("secs_left") <= 120))
    endgame = (pl.col("period") > 4) | ((pl.col("period") == 4) & (pl.col("secs_left") <= 240))
    take = events.filter((pl.col("subType") == "Personal Take") & last2).with_columns(
        trailing=pl.when(pl.col("location") == "h").then(pl.col("score_h") < pl.col("score_a"))
                   .otherwise(pl.col("score_a") < pl.col("score_h")))
    takes = take.group_by("gameId").agg(take_fouls_last2=pl.len(),
                                        take_fouls_trailing_last2=pl.col("trailing").sum())

    sc = scoring_rows(events)
    pts = sc.group_by("gameId").agg(
        endgame_pts=pl.col("pts").filter(endgame).sum(),
        endgame_ft_pts=pl.col("pts").filter(endgame & pl.col("is_ft")).sum(),
        q1_q3_pts=pl.col("pts").filter(pl.col("period") <= 3).sum(),
        q1_q3_ft_pts=pl.col("pts").filter((pl.col("period") <= 3) & pl.col("is_ft")).sum(),
        last_score_ft=pl.col("is_ft").sort_by("seq").last())

    # The winner's last go-ahead: the last scoring row after which the
    # winner leads, preceded by a row where it did not.
    g = games.select("gameId", "final_home", "final_away", "periods")
    lead = (sc.join(g, on="gameId", validate="m:1")
            .with_columns(w_lead=pl.when(pl.col("final_home") > pl.col("final_away"))
                                   .then(pl.col("score_h") - pl.col("score_a"))
                                   .otherwise(pl.col("score_a") - pl.col("score_h")))
            .sort("gameId", "seq")
            .with_columns(prev=pl.col("w_lead").shift(1).over("gameId").fill_null(0))
            .filter((pl.col("w_lead") > 0) & (pl.col("prev") <= 0))
            .group_by("gameId").agg(pl.all().sort_by("seq").last())
            .select("gameId", decided_late=(pl.col("period") == pl.col("periods"))
                                           & (pl.col("secs_left") <= 60)))

    margin2 = (events.filter((pl.col("period") == 4) & (pl.col("secs_left") >= 120))
               .group_by("gameId").agg(pl.all().sort_by("seq").last())
               .select("gameId", margin_at_2min=(pl.col("score_h") - pl.col("score_a")).abs()))

    out = (games.select("gameId", "league", "season", "season_type", "periods")
           .with_columns(overtime=pl.col("periods") > 4)
           .join(margin2, on="gameId", how="left", validate="1:1")
           .join(takes, on="gameId", how="left", validate="1:1")
           .join(pts, on="gameId", how="left", validate="1:1")
           .join(lead, on="gameId", how="left", validate="1:1")
           .join(wall_clock(games["gameId"].to_list()), on="gameId", how="left", validate="1:1")
           .with_columns(pl.col("take_fouls_last2", "take_fouls_trailing_last2").fill_null(0))
           .sort("gameId"))
    return out


def summarize(pg: pl.DataFrame) -> pl.DataFrame:
    def agg(frame, keys):
        return frame.group_by(keys).agg(
            games=pl.len(),
            overtime_rate=pl.col("overtime").mean(),
            take_fouls_per_game=pl.col("take_fouls_last2").mean(),
            games_with_trailing_take=(pl.col("take_fouls_trailing_last2") > 0).mean(),
            endgame_ft_share=pl.col("endgame_ft_pts").sum() / pl.col("endgame_pts").sum(),
            q1_q3_ft_share=pl.col("q1_q3_ft_pts").sum() / pl.col("q1_q3_pts").sum(),
            last_score_ft_rate=pl.col("last_score_ft").mean(),
            decided_late_rate=pl.col("decided_late").mean(),
            wall_games=pl.col("real_secs_q4_last2").is_not_null().sum(),
            median_real_min_q4_last2=pl.col("real_secs_q4_last2").median() / 60,
            close_games=(pl.col("margin_at_2min") <= 5).sum(),
            median_real_min_q4_last2_close=pl.col("real_secs_q4_last2")
                                             .filter(pl.col("margin_at_2min") <= 5).median() / 60,
            median_real_min_q4_last2_not_close=pl.col("real_secs_q4_last2")
                                                 .filter(pl.col("margin_at_2min") > 5).median() / 60,
            median_real_min_q3_mid2=pl.col("real_secs_q3_mid2").median() / 60,
        )
    s = agg(pg, ["league", "season", "season_type"])
    p = agg(pg, ["league", "season_type"]).with_columns(season=pl.lit("pooled"))
    a = agg(pg, ["league"]).with_columns(season=pl.lit("pooled"), season_type=pl.lit("all"))
    return pl.concat([s, p.select(s.columns), a.select(s.columns)]).sort(
        "league", "season", "season_type")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    events = pl.read_parquet(EVENTS)
    games = pl.read_csv(GAMES, schema_overrides={"gameId": pl.Utf8})
    pg = per_game(events, games)
    summ = summarize(pg)
    problems = []
    if pg.height != games.height:
        problems.append(f"endgame_games has {pg.height} rows, games.csv {games.height}")
    if pg["real_secs_q4_last2"].null_count() > 0.01 * pg.height:
        problems.append(f"wall clock missing for {pg['real_secs_q4_last2'].null_count()} games")
    print(f"wall clock: {pg['real_secs_q4_last2'].null_count()} games without a usable "
          f"final 2:00, {pg['real_secs_q3_mid2'].null_count()} without a Q3 comparison")
    with pl.Config(tbl_rows=30, tbl_cols=20, tbl_width_chars=250):
        print(summ)
    for p in problems:
        print("PROBLEM", p)
    outs = [(OUT_GAMES, pg, {"gameId": pl.Utf8}), (OUT_SUMMARY, summ, None)]
    if args.check:
        problems += [w for path, fresh, so in outs if (w := checks.matches(path, fresh, so))]
        print("06_endgame_audit check:", "FAILED" if problems else "PASSED",
              f"({pg.height:,} games, {len(problems)} problems)")
        return 1 if problems else 0
    for path, fresh, _ in outs:
        fresh.write_csv(path)
    print("wrote", ", ".join(p.name for p, _, _ in outs))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
