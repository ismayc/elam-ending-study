"""Fetch NBA liveData play-by-play for every playoff game in the study.

liveData is served from the league's media S3 bucket, which answered from this
machine on October 19, 2026 while stats.nba.com, stats.wnba.com, and
cdn.nba.com did not. It is a second, independent feed (running score on every
action), and the only reachable source for the WNBA 2026 playoffs.

Game IDs come from playoff-series-study's LeagueGameLog harvest. WNBA 2026
was harvested mid-playoffs, so later Finals games are probed by ID
(1042600302, 1042600303, ...) until one is missing.

Files land in data/raw/live/<gameId>.json exactly as served; existing files
are skipped, so the script is resumable.
"""
from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
GAMELOG_DIR = ROOT.parent / "playoff-series-study" / "data" / "raw" / "gamelogs"
OUT = ROOT / "data" / "raw" / "live"
URL = ("https://nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/"
       "{league}/liveData/playbyplay/playbyplay_{game_id}.json")
PLAYOFF_LOGS = ["nba_2024_po", "nba_2025_po", "nba_2026_po",
                "wnba_2024_po", "wnba_2025_po", "wnba_2026_po"]


def fetch(game_id: str) -> str:
    """'ok', 'cached', or 'missing'."""
    path = OUT / f"{game_id}.json"
    if path.exists():
        return "cached"
    league = "NBA" if game_id.startswith("00") else "WNBA"
    req = urllib.request.Request(URL.format(league=league, game_id=game_id),
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return "missing"
        raise
    path.write_bytes(body)
    time.sleep(0.5)
    return "ok"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ids = sorted(pl.concat([pl.read_csv(GAMELOG_DIR / f"{n}.csv", infer_schema_length=0)
                            .select(pl.col("GAME_ID").str.zfill(10)) for n in PLAYOFF_LOGS])
                 ["GAME_ID"].unique().to_list())
    status = {g: fetch(g) for g in ids}

    # WNBA 2026 Finals games after the harvest: the Finals are round 3, series
    # 0, so IDs run 10426003 + 0 + game number.
    game = max(int(g[-1]) for g in ids if g.startswith("10426003"))
    while game < 7:
        game += 1
        g = f"104260030{game}"
        status[g] = fetch(g)
        if status[g] == "missing":
            break

    counts = pl.DataFrame({"gameId": list(status), "status": list(status.values())})
    print(counts.group_by(pl.col("gameId").str.slice(0, 5).alias("prefix"), "status")
          .len().sort("prefix", "status"))
    missing = [g for g, s in status.items() if s == "missing"]
    print("missing:", missing)
    # The probe past the last Finals game is expected to be missing; any other
    # missing game is a problem.
    unexpected = [g for g in missing if g in ids]
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
