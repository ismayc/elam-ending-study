"""Shared --check helper: does a fresh build match the committed table?

Exact for text and integers; floats within TOL, because polars group_by sums
in whatever row order its threads see, so a rebuild moves the last bits of a
sum (1.8e-12 on race_summary.csv, October 19, 2026). Same tolerance as
03_reconcile.py.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

TOL = 1e-9


def matches(path: Path, fresh: pl.DataFrame, schema_overrides: dict | None = None) -> str | None:
    """None if path holds the same table as fresh, else the reason it does not."""
    if not path.exists():
        return f"{path.name} missing"
    old = pl.read_csv(path, schema_overrides=schema_overrides)
    new = pl.read_csv(fresh.write_csv().encode(), schema_overrides=schema_overrides)
    if old.columns != new.columns or old.height != new.height:
        return f"{path.name}: shape or columns differ from a fresh build"
    for c in old.columns:
        a, b = old[c], new[c]
        if a.dtype.is_float() or b.dtype.is_float():
            a, b = a.cast(pl.Float64), b.cast(pl.Float64)
            bad = ((a - b).abs() > TOL) | (a.is_null() != b.is_null())
        else:
            bad = (a.cast(pl.Utf8) != b.cast(pl.Utf8)).fill_null(a.is_null() != b.is_null())
        if bad.any():
            return f"{path.name}.{c}: {int(bad.sum())} cells differ from a fresh build"
    return None
