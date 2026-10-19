# Elam Ending study

How would the Elam Ending have changed NBA and WNBA results over the last three
seasons? Personal research in the basketball-data-science family (see
`../hub/ideas/historical-analysis-ideas.md`, "Elam Ending counterfactual").
Design decisions and their dates live in `docs/design.md`.

## Data context

- **Scope:** NBA 2023-24, 2024-25, 2025-26 and WNBA 2024, 2025, 2026, regular
  season and playoffs (play-in and NBA Cup final excluded: no V3 rows). WNBA
  2026 playoffs come from liveData (`feed` column) and are partial until the
  Finals end (see `DATA_SOURCES.md`).
- **Grain:** events: one `PlayByPlayV3` action (`gameId`, `actionNumber`);
  games: one game; possessions: one pbpstats possession (`game_id`,
  `PERIOD`, `start_secs`).
- **Keys and joins:** events to games on `gameId`, many to one. Game IDs are
  10-character strings (`002`/`004` NBA regular/playoff, `102`/`104` WNBA);
  the possession tables store them as integers without leading zeros, so pad
  before joining.
- **Elam rule (decided October 19, 2026):** trigger at the first dead ball
  with under 4:00 left in Q4 (both leagues); target = leading score + 8 (tied:
  either score + 8); overtime games replay from the Q4 trigger like any game.
  The dead-ball event set is defined in `docs/design.md`.
- **Known issues:** every `PlayByPlayV3` column is text; `clock` is ISO 8601
  (`PT03M59.00S`); V3 can insert late events out of order, so sort by period
  then clock, not `actionNumber`, when order matters. Running scores follow
  the three score-stamp rules in `01_import.py` `prepare()` (see "Data
  checks" in `docs/design.md`), never a plain forward fill.
- **Sources of truth:** the final score in each game's last event must equal
  the LeagueGameLog final (playoff-series-study `data/raw/gamelogs/`). A game
  that fails this is listed by the check, never silently repaired.
- **Suspicious results:** a flip rate of 0% or above 25%, a trigger missing
  from more than a handful of games, or a target reached by both teams on the
  same event means stop and check.

Data sources, licenses, and retrieval dates: see `DATA_SOURCES.md`. Do not use
a dataset whose license cell is empty. Raw rows stay local; publish derived,
game-level results only.

## How work is done here

- Family layout, not the new-project default: `python/NN_*.py` scripts, an R
  mirror in `R/` for every reconciled output, `tests/python` and `tests/R`,
  `output/` for derived tables, `run_checks.sh` as the gate. Python uses
  polars and plotly; the shared venv is `../.venv`.
- Python and R must agree on every reconciled cell within 1e-9, so methods are
  deterministic: tier 2 is an exact dynamic program, not a Monte Carlo
  simulation.
- **Plan mode first** for any step that drops or filters games, deletes or
  overwrites files, joins tables, or changes the Elam rule. Show the plan and
  wait.
- `data/raw/` holds files exactly as downloaded and is never edited. Derived
  data goes in `data/` (local) or `output/` (committed, game-level only).
- Before reporting: rerun the script and confirm the numbers match, recompute
  one headline number a different way, and report row and game counts before
  and after every join or filter.
- Label anything not checked against the data as unverified.
- Evals or demos of agent behavior run with `claude -p --safe-mode` and record
  the model and flags with the result.
