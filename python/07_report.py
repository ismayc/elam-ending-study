"""Write the README's results section from the output tables, so no number in
it is typed by hand. Replaces the text between <!-- gen:results --> and
<!-- /gen:results -->. --check fails if the README is out of date.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
README = ROOT / "README.md"
START, END = "<!-- gen:results -->", "<!-- /gen:results -->"
LEAGUE = {"nba": "NBA", "wnba": "WNBA"}
STYPE = {"regular": "regular season", "playoffs": "playoffs"}


def pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:.{digits}f}%"


def results() -> str:
    rep = pl.read_csv(OUT / "replay_summary.csv").filter(pl.col("season") == "pooled",
                                                         pl.col("season_type") != "all")
    race = pl.read_csv(OUT / "race_summary.csv").filter(pl.col("season") == "pooled",
                                                        pl.col("season_type") != "all")
    marg = pl.read_csv(OUT / "race_by_margin.csv")
    cal = pl.read_csv(OUT / "race_calibration.csv").filter(pl.col("version") == "league")
    end = pl.read_csv(OUT / "endgame_summary.csv").filter(pl.col("season") == "pooled",
                                                          pl.col("season_type") != "all")
    games = pl.read_csv(OUT / "games.csv", schema_overrides={"gameId": pl.Utf8})

    w26 = games.filter(pl.col("gameId").str.starts_with("10426")).height
    lines = [f"Coverage: {games.height:,} games, every regular-season game of NBA 2023-24 to "
             "2025-26 and WNBA 2024 to 2026 plus every playoff game played "
             f"({games.filter(pl.col('season_type') == 'playoffs').height} games, including "
             f"{w26} from the 2026 WNBA playoffs as of the last fetch). Each tier is computed "
             "in Python and again in R, and the two agree on every cell.", ""]

    lines += ["**Tier 1, literal replay.** Each game's real play-by-play, read under the "
              "Elam rule from the trigger on.", "",
              "| League | Games | Winner changes | Neither team reaches the target |",
              "|---|---|---|---|"]
    for r in rep.sort("league", "season_type", descending=[False, True]).iter_rows(named=True):
        lines.append(f"| {LEAGUE[r['league']]} {STYPE[r['season_type']]} | {r['games']:,} | "
                     f"{r['flipped']} ({pct(r['flip_rate'])}) | "
                     f"{r['unresolved']:,} ({pct(r['unresolved_rate'], 0)}) |")
    lines += ["", "A bound, not a forecast: the real teams played to the clock. Unresolved "
              "games are ones where the leader added fewer than 8 points before the buzzer.", ""]

    allbin = cal.filter(pl.col("bin") == "all").row(0, named=True)
    brier = cal.filter(pl.col("bin") == "brier").row(0, named=True)
    worst = (cal.filter(~pl.col("bin").is_in(["all", "brier"]))
             .select((pl.col("mean_predicted") - pl.col("observed")).abs().max()).item())
    lines += ["**Tier 2, race to the target.** An exact model of the race from each game's "
              "trigger, built from clock-neutral points per possession. On "
              f"{allbin['races']:,} real races to leader + 8 in the second and third quarters "
              f"it predicted {pct(allbin['mean_predicted'])} for the favorite against "
              f"{pct(allbin['observed'])} observed (no bin off by more than "
              f"{100 * worst:.1f} points; Brier {brier['mean_predicted']:.3f} against "
              f"{brier['observed']:.3f} for a constant rate).", "",
              "| League | Leader at the trigger wins, clock (real) | Leader wins, Elam (model) |",
              "|---|---|---|"]
    for r in race.sort("league", "season_type", descending=[False, True]).iter_rows(named=True):
        lines.append(f"| {LEAGUE[r['league']]} {STYPE[r['season_type']]} | "
                     f"{pct(r['leader_win_rate_clock'])} | {pct(r['leader_win_rate_elam_league'])} |")
    m = marg.filter(pl.col("league") == "nba", pl.col("margin") == "11-15").row(0, named=True)
    po = race.filter(pl.col("season_type") == "playoffs")
    lines += ["", "In the regular season the rule barely moves the leader's odds. The playoff "
              f"rows rest on {po['led_games'].sum()} games with a leader at the trigger, too "
              "few to read much into. The clearest shift is at big leads: NBA teams ahead "
              f"by 11 to 15 at the trigger won {pct(m['clock'])} "
              f"under the clock (95% interval {pct(m['clock_lo'])} to {pct(m['clock_hi'])}) "
              f"against {pct(m['elam_league'])} in the model, since no clock runs out for them. "
              "By margin: `output/race_by_margin.csv`.", ""]

    lines += ["**Tier 3, the endgame audit.** What the clock does to real endings.", "",
              "| League | Overtime | Free-throw share of points, last 4:00 + OT (Q1-Q3) | "
              "Games with a take foul by the trailing team, last 2:00 | Real minutes for the "
              "last 2:00, close games (others) |",
              "|---|---|---|---|---|"]
    for r in end.sort("league", "season_type", descending=[False, True]).iter_rows(named=True):
        lines.append(f"| {LEAGUE[r['league']]} {STYPE[r['season_type']]} | "
                     f"{pct(r['overtime_rate'])} | {pct(r['endgame_ft_share'], 0)} "
                     f"({pct(r['q1_q3_ft_share'], 0)}) | {pct(r['games_with_trailing_take'], 0)} | "
                     f"{r['median_real_min_q4_last2_close']:.1f} "
                     f"({r['median_real_min_q4_last2_not_close']:.1f}) |")
    lines += ["", "Close games are within 5 points at 2:00 of Q4; minutes are medians of "
              "liveData wall-clock stamps. Elam would abolish the overtime and remove the "
              "clock that the take fouls and the long final minutes serve."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = README.read_text()
    if START not in text or END not in text:
        print("README has no gen:results markers")
        return 1
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{START}\n{results()}\n{END}{tail}"
    if args.check:
        ok = new == text and "{" not in results() and "}" not in results()
        print("07_report check:", "PASSED" if ok else "FAILED (README results are stale)")
        return 0 if ok else 1
    # A brace left in the output means an f-string prefix went missing (it
    # happened once: "{pct(m['clock'])}" reached the README).
    if "{" in results() or "}" in results():
        print("generated results contain a raw brace: a missing f-string prefix")
        return 1
    README.write_text(new)
    print("wrote README.md results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
