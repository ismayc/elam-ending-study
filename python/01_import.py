"""Build one ordered events table for every game in the study, and check each
game's final score against an independent source.

Inputs (all local, never committed):
- regular season: playbyplay-study's PlayByPlayV3 cache, one parquet per game
  (../playbyplay-study/data/raw_pbp/), NBA 2023-24 to 2025-26, WNBA 2024-2026;
- playoffs: the shufinskiy nbastatsv3_po_* archives in data/raw/ (the stats
  hosts are blocked; see docs/findings/playoff-pbp-source.md).

Checks against independent sources:
- every game's final score against LeagueGameLog points (playoff-series-study
  data/raw/gamelogs/);
- regular season only, the score at every clock instant from 5:00 of Q4 on
  against the NBA liveData feed (cached by playbyplay-study as
  data/pbpstats_live/pbp/live_<id>.json). When the two feeds disagree, the
  game passes only if LeagueGameLog sides with V3.

Writes data/events.parquet (event rows stay local) and output/games.csv (one
row per game). --check rebuilds in memory and fails on any final-score
mismatch, unexcused endgame disagreement, wrong game count, or a
games.csv that differs from a fresh build.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT.parent
PBP_DIR = FAMILY / "playbyplay-study" / "data" / "raw_pbp"
LIVE_DIR = FAMILY / "playbyplay-study" / "data" / "pbpstats_live" / "pbp"
GAMELOG_DIR = FAMILY / "playoff-series-study" / "data" / "raw" / "gamelogs"
RAW_DIR = ROOT / "data" / "raw"
EVENTS = ROOT / "data" / "events.parquet"
GAMES = ROOT / "output" / "games.csv"

# Game-ID prefix -> games expected. Regular season from playbyplay-study's
# coverage; playoffs from playoff-series-study's game log (checked
# October 19, 2026). WNBA 2026 playoffs are absent from every reachable source.
EXPECTED = {
    "00223": 1230, "00224": 1230, "00225": 1230,
    "10224": 240, "10225": 286, "10226": 330,
    "00423": 82, "00424": 84, "00425": 85,
    "10424": 22, "10425": 24,
}
PLAYOFF_ARCHIVES = [
    "nbastatsv3_po_2023", "nbastatsv3_po_2024", "nbastatsv3_po_2025",
    "wnba_nbastatsv3_po_2024", "wnba_nbastatsv3_po_2025",
]
KEEP = ["gameId", "actionNumber", "clock", "period", "teamId", "location",
        "actionType", "subType", "description", "shotResult", "isFieldGoal",
        "scoreHome", "scoreAway"]


def game_meta(game_id: pl.Expr) -> list[pl.Expr]:
    """League, season label, and season type from the 10-character game ID:
    "0022500001" is NBA, regular season, 2025-26; "1042400101" is WNBA,
    playoffs, 2024."""
    yy = game_id.str.slice(3, 2).cast(pl.Int32)
    league = pl.when(game_id.str.slice(0, 2) == "00").then(pl.lit("nba")).otherwise(pl.lit("wnba"))
    season = (pl.when(league == "nba")
              .then(pl.format("20{}-{}", yy.cast(pl.Utf8).str.zfill(2),
                              (yy + 1).cast(pl.Utf8).str.zfill(2)))
              .otherwise(pl.format("20{}", yy.cast(pl.Utf8).str.zfill(2))))
    stype = pl.when(game_id.str.slice(2, 1) == "4").then(pl.lit("playoffs")).otherwise(pl.lit("regular"))
    return [league.alias("league"), season.alias("season"), stype.alias("season_type")]


def read_regular() -> pl.DataFrame:
    files = sorted(p for p in PBP_DIR.glob("*.parquet") if p.name[:5] in EXPECTED)
    # diagonal: the feed adds or drops columns between seasons
    return pl.concat([pl.read_parquet(f).select(KEEP) for f in files], how="diagonal")


def read_playoffs() -> pl.DataFrame:
    frames = []
    for name in PLAYOFF_ARCHIVES:
        with tarfile.open(RAW_DIR / f"{name}.tar.xz") as tar:
            member = tar.getmember(f"{name}.csv")
            raw = tar.extractfile(member).read()
        df = pl.read_csv(io.BytesIO(raw), infer_schema_length=0)
        # The archive drops leading zeros from game IDs and leaves empty text
        # as null; match the harvested cache, where both are text.
        df = df.with_columns(pl.col("gameId").str.zfill(10)).select(KEEP)
        frames.append(df.with_columns(pl.all().fill_null("")))
    return pl.concat(frames, how="diagonal")


def prepare(df: pl.DataFrame) -> pl.DataFrame:
    """Typed events in game-clock order with running scores. Same ordering
    rule as playbyplay-study's prepare_events: clock first, actionNumber only
    to break ties, because the feed inserts late events with a high
    actionNumber but an early clock."""
    mins = pl.col("clock").str.extract(r"PT(\d+)M", 1).cast(pl.Float64)
    secs = pl.col("clock").str.extract(r"M([\d.]+)S", 1).cast(pl.Float64)
    # Only scoring rows set the score. "Instant Replay" rows also carry a score
    # stamp, but it is a snapshot from another moment: in 0022300010 a replay
    # row at 4:17 of Q2 reads 53-44 right after Tatum's free throws made it
    # 55-44 (the review took the points off a later-voided play or simply
    # stamped the pre-review score; either way the stamp is not a score
    # change). Taken at face value those stamps made the running score fall
    # in 308 of 4,843 games. Period rows repeat the score and add nothing.
    # And a scoring row sets only the scoring team's score: in 0022500527
    # Camara's (home) second free throw at 4:32 of Q4 is stamped 93-91, but
    # the away side was still on 89 (liveData agrees; the 91 is the next away
    # basket, stamped early). Same in 1022600019 with Bueckers at 0:13.9.
    scoring = pl.col("actionType").is_in(["Made Shot", "Free Throw"])
    df = df.with_columns(
        scoreHome=pl.when(scoring & (pl.col("location") == "h"))
                    .then(pl.col("scoreHome")).otherwise(pl.lit("")),
        scoreAway=pl.when(scoring & (pl.col("location") == "v"))
                    .then(pl.col("scoreAway")).otherwise(pl.lit("")),
    )
    df = df.with_columns(
        period=pl.col("period").cast(pl.Int32),
        actionNumber=pl.col("actionNumber").cast(pl.Int64),
        secs_left=mins * 60 + secs,
        score_h=pl.when(pl.col("scoreHome") == "").then(None)
                  .otherwise(pl.col("scoreHome")).cast(pl.Int32, strict=False),
        score_a=pl.when(pl.col("scoreAway") == "").then(None)
                  .otherwise(pl.col("scoreAway")).cast(pl.Int32, strict=False),
    ).filter(pl.col("secs_left").is_not_null()).sort(
        ["gameId", "period", "secs_left", "actionNumber"],
        descending=[False, False, True, False])
    # Running maximum, not a forward fill. Scoring rows that share one clock
    # reading are not always in actionNumber order: in 0022300055 at 3:54 of
    # Q4, Mitchell's technical free throw (#655, stamped 124) sorts after his
    # and-one free throw (#647, stamped 126), and a forward fill carried 124
    # for the next 70 seconds. The NBA liveData feed orders the same rows
    # correctly and reads 126. A score never falls in a real game, so the
    # running maximum is the score; a genuinely rescinded basket would leave a
    # wrong final, which the final-score check below reports.
    df = df.with_columns(
        score_h=pl.col("score_h").fill_null(0).cum_max().over("gameId"),
        score_a=pl.col("score_a").fill_null(0).cum_max().over("gameId"),
        seq=pl.int_range(pl.len()).over("gameId"),
    )
    return df.with_columns(game_meta(pl.col("gameId"))).drop("scoreHome", "scoreAway", "clock")


def home_away(events: pl.DataFrame) -> pl.DataFrame:
    """Home and away team IDs from the events' location flags."""
    side = (events.filter(pl.col("location").is_in(["h", "v"]) & (pl.col("teamId") != "0")
                          & (pl.col("teamId") != ""))
            .group_by("gameId", "location").agg(pl.col("teamId").mode().first()))
    return (side.pivot(on="location", index="gameId", values="teamId")
            .rename({"h": "home_team_id", "v": "away_team_id"}))


def live_scores(game_ids: list[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    """From the NBA liveData feed: each game's final score, and the score at
    the end of every clock instant from 5:00 of Q4 on (overtime included),
    the stretch the Elam replay reads."""
    finals, instants = [], []
    for g in game_ids:
        path = LIVE_DIR / f"live_{g}.json"
        if not path.exists():
            finals.append({"gameId": g, "off_home": None, "off_away": None})
            continue
        actions = json.loads(path.read_text())["game"]["actions"]
        finals.append({"gameId": g, "off_home": int(actions[-1]["scoreHome"]),
                       "off_away": int(actions[-1]["scoreAway"])})
        for a in actions:
            m, s = a["clock"][2:].rstrip("S").split("M")
            left = int(m) * 60 + float(s)
            if a["period"] > 4 or (a["period"] == 4 and left <= 300):
                instants.append((g, a["period"], left, int(a["scoreHome"]), int(a["scoreAway"])))
    finals = pl.DataFrame(finals, schema={"gameId": pl.Utf8, "off_home": pl.Int32,
                                          "off_away": pl.Int32})
    # Last action of each instant, in the feed's own order.
    instants = (pl.DataFrame(instants, orient="row", schema={
                    "gameId": pl.Utf8, "period": pl.Int32, "secs_left": pl.Float64,
                    "live_h": pl.Int32, "live_a": pl.Int32})
                .group_by("gameId", "period", "secs_left", maintain_order=True).last())
    return finals, instants


def official_finals() -> pl.DataFrame:
    """Team points per game from LeagueGameLog (playoff-series-study's raw
    harvest), one row per team-game. Matched to home and away by team ID, not
    by MATCHUP's "vs." marker: ten neutral-site games (0022400147,
    0022401230, and others) list both teams with "@". Files are named by the
    season's end year for the NBA (nba_2025_rs.csv is 2024-25) and by the
    season for the WNBA."""
    names = ["nba_2024", "nba_2025", "nba_2026", "wnba_2024", "wnba_2025", "wnba_2026"]
    files = [GAMELOG_DIR / f"{n}_{t}.csv" for n in names for t in ("rs", "po")]
    log = pl.concat([pl.read_csv(f, infer_schema_length=0).select("GAME_ID", "TEAM_ID", "PTS")
                     for f in files if f.exists()])
    return (log.select(gameId=pl.col("GAME_ID").str.zfill(10), team_id=pl.col("TEAM_ID"),
                       pts=pl.col("PTS").cast(pl.Float64).cast(pl.Int32))
            .filter(pl.col("gameId").str.slice(0, 5).is_in(list(EXPECTED))))


def build() -> tuple[pl.DataFrame, pl.DataFrame, list[str]]:
    events = prepare(pl.concat([read_regular(), read_playoffs()], how="diagonal"))
    problems: list[str] = []

    counts = events.group_by(pl.col("gameId").str.slice(0, 5).alias("prefix")).agg(
        n=pl.col("gameId").n_unique())
    got = dict(counts.iter_rows())
    for prefix, n in EXPECTED.items():
        if got.get(prefix) != n:
            problems.append(f"game count {prefix}: expected {n}, got {got.get(prefix)}")

    finals = (events.group_by("gameId").agg(
                  pl.col("league").first(), pl.col("season").first(),
                  pl.col("season_type").first(),
                  final_home=pl.col("score_h").last(), final_away=pl.col("score_a").last(),
                  periods=pl.col("period").max())
              .join(home_away(events), on="gameId", how="left", validate="1:1"))
    log = official_finals()
    games = (finals
             .join(log.rename({"team_id": "home_team_id", "pts": "off_home"}),
                   on=["gameId", "home_team_id"], how="left", validate="1:1")
             .join(log.rename({"team_id": "away_team_id", "pts": "off_away"}),
                   on=["gameId", "away_team_id"], how="left", validate="1:1")).with_columns(
        final_ok=((pl.col("final_home") == pl.col("off_home"))
                  & (pl.col("final_away") == pl.col("off_away"))).fill_null(False))
    for row in games.filter(~pl.col("final_ok")).iter_rows(named=True):
        problems.append(f"final mismatch {row['gameId']}: pbp {row['final_home']}-"
                        f"{row['final_away']}, LeagueGameLog {row['off_home']}-{row['off_away']}")

    # Endgame cross-feed check (regular season, where liveData is cached): the
    # score at the end of every clock instant from 5:00 of Q4 on. Instants,
    # not rows, because same-instant row order differs between the feeds.
    # Playoffs have no second feed here and rest on the final-score check.
    reg_ids = finals.filter(pl.col("season_type") == "regular")["gameId"].to_list()
    live_finals, live_instants = live_scores(reg_ids)
    v3_instants = (events.filter(pl.col("gameId").is_in(reg_ids)
                                 & ((pl.col("period") > 4)
                                    | ((pl.col("period") == 4) & (pl.col("secs_left") <= 300))))
                   .group_by("gameId", "period", "secs_left").agg(
                       pl.col("score_h").last(), pl.col("score_a").last()))
    endgame = v3_instants.join(live_instants, on=["gameId", "period", "secs_left"],
                               how="inner", validate="1:1")
    differ = endgame.group_by("gameId").agg(
        live_instants=pl.len(),
        live_instants_differ=((pl.col("score_h") != pl.col("live_h"))
                              | (pl.col("score_a") != pl.col("live_a"))).sum())
    print(f"endgame cross-feed: {endgame.height:,} shared instants in "
          f"{endgame['gameId'].n_unique():,} of {len(reg_ids):,} regular-season games; "
          f"{differ['live_instants_differ'].sum()} differ in "
          f"{(differ['live_instants_differ'] > 0).sum()} games")
    if endgame["gameId"].n_unique() < 0.99 * len(reg_ids):
        problems.append("endgame cross-feed covers under 99% of regular-season games")

    # A disagreement is the feed's error, not V3's, only when LeagueGameLog
    # sides with V3 on the final and not with liveData (October 19, 2026:
    # 0022400072 and 0022500029, where liveData is one point short, and
    # 1022400138, whose liveData file stops at 55-59).
    games = (games.join(live_finals.rename({"off_home": "live_home", "off_away": "live_away"}),
                        on="gameId", how="left", validate="1:1")
             .join(differ, on="gameId", how="left", validate="1:1")
             .with_columns(pl.col("live_instants", "live_instants_differ").fill_null(0))
             .with_columns(live_final_ok=(pl.col("live_home") == pl.col("off_home"))
                                         & (pl.col("live_away") == pl.col("off_away")))
             .with_columns(endgame_check=pl.when(pl.col("season_type") == "playoffs")
                                           .then(pl.lit("no second feed"))
                                           .when(pl.col("live_instants") == 0)
                                           .then(pl.lit("no shared instants"))
                                           .when(pl.col("live_instants_differ") == 0)
                                           .then(pl.lit("agrees"))
                                           .when(pl.col("final_ok") & ~pl.col("live_final_ok"))
                                           .then(pl.lit("liveData wrong"))
                                           .otherwise(pl.lit("UNRESOLVED")))
             .drop("live_home", "live_away", "live_final_ok")
             .sort("gameId"))
    for g in games.filter(pl.col("endgame_check") == "UNRESOLVED")["gameId"].to_list():
        problems.append(f"endgame score differs from liveData in {g}, and LeagueGameLog "
                        f"does not settle it")
    return events, games, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="rebuild in memory, compare with output/games.csv, write nothing")
    args = ap.parse_args()

    events, games, problems = build()
    print(f"events: {events.height:,} rows, {events['gameId'].n_unique():,} games")
    print(games.group_by("league", "season", "season_type").agg(
        games=pl.len(), final_ok=pl.col("final_ok").sum(),
        overtime=(pl.col("periods") > 4).sum()).sort("league", "season", "season_type"))
    for p in problems:
        print("PROBLEM", p)

    if args.check:
        if GAMES.exists():
            committed = pl.read_csv(GAMES, schema_overrides={"gameId": pl.Utf8,
                                    "home_team_id": pl.Utf8, "away_team_id": pl.Utf8})
            if not committed.equals(games.select(committed.columns)):
                problems.append("output/games.csv differs from a fresh build")
        else:
            problems.append("output/games.csv missing")
        print("01_import check:", "FAILED" if problems else "PASSED",
              f"({games.height:,} games, {len(problems)} problems)")
        return 1 if problems else 0

    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    GAMES.parent.mkdir(parents=True, exist_ok=True)
    events.write_parquet(EVENTS)
    games.write_csv(GAMES)
    print(f"wrote {EVENTS.relative_to(ROOT)} and {GAMES.relative_to(ROOT)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
