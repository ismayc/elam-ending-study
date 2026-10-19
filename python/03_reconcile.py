"""Verify the R and Python replays agree, cell by cell.

Two independent implementations of the rule in docs/design.md
(python/02_replay.py and R/02_replay.R). Every compared column must match
exactly (text and integers) or within 1e-9 (rates). Non-zero exit on any
mismatch, so this gates a commit.

Run after both scripts:  python python/03_reconcile.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
TOL = 1e-9

# (python file, R file, join keys)
TABLES = [
    ("replay_games.csv", "replay_games_r.csv", ["gameId"]),
    ("replay_summary.csv", "replay_summary_r.csv", ["league", "season", "season_type"]),
]


def compare(py_name: str, r_name: str, keys: list[str]) -> list[str]:
    read = lambda p: pl.read_csv(OUT / p, infer_schema_length=0)  # noqa: E731
    py, r = read(py_name), read(r_name)
    cols = [c for c in r.columns if c not in keys]
    missing = [c for c in cols if c not in py.columns]
    if missing:
        return [f"{r_name}: columns not in {py_name}: {missing}"]
    if py.height != r.height:
        return [f"{py_name}: {py.height} rows in Python, {r.height} in R"]
    j = py.select(keys + cols).join(r, on=keys, how="full", suffix="_r", coalesce=True)
    problems = []
    for c in cols:
        a, b = j[c], j[f"{c}_r"]
        # R writes TRUE/FALSE, polars true/false; compare case-blind. Numbers
        # compare as floats so "215" and "215.0" agree.
        num_a = a.cast(pl.Float64, strict=False)
        num_b = b.cast(pl.Float64, strict=False)
        both_num = num_a.is_not_null() & num_b.is_not_null()
        num_bad = both_num & ((num_a - num_b).abs() > TOL)
        txt_bad = ~both_num & (a.fill_null("").str.to_lowercase()
                               != b.fill_null("").str.to_lowercase())
        n = int((num_bad | txt_bad).sum())
        if n:
            first = j.filter(num_bad | txt_bad).select(keys + [c, f"{c}_r"]).row(0)
            problems.append(f"{py_name}.{c}: {n} cells differ, first {first}")
    print(f"{py_name}: {py.height:,} rows x {len(cols)} columns compared, "
          f"{len(problems)} columns differ")
    return problems


def main() -> int:
    problems = [p for t in TABLES for p in compare(*t)]
    for p in problems:
        print("MISMATCH", p)
    print("03_reconcile:", "FAILED" if problems else "PASSED")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
