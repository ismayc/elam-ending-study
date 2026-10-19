#!/bin/bash
# Every check in this repo: unit tests, then the study's validation gates.
# Non-zero exit on any failure. PY overrides the interpreter (the family
# orchestrator sets it to the shared venv).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-../.venv/bin/python}

echo "=== unit tests: Python (pytest) ==="
$PY -m pytest tests/python -q

echo
echo "=== import: finals vs LeagueGameLog, endgame vs liveData ==="
$PY -I python/01_import.py --check | tail -1

echo
echo "=== replay: outputs reproduce ==="
$PY -I python/02_replay.py --check | tail -1


echo
echo "=== possessions: points coverage and distributions reproduce ==="
$PY -I python/04_possessions.py --check | tail -1

echo
echo "=== race model: outputs reproduce ==="
$PY -I python/05_race_model.py --check | tail -1

echo
echo "=== endgame audit: outputs reproduce ==="
$PY -I python/06_endgame_audit.py --check | tail -1

echo
echo "=== reconciliation: R vs Python, every tier ==="
Rscript R/02_replay.R >/dev/null
Rscript R/05_race_model.R >/dev/null
Rscript R/06_endgame_audit.R >/dev/null
$PY -I python/03_reconcile.py | tail -1

echo
echo "=== report: README results match the outputs ==="
$PY -I python/07_report.py --check
