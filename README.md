# Elam Ending study

How would the Elam Ending have changed NBA and WNBA results? This study
replays the last three seasons of each league (NBA 2023-24 to 2025-26, WNBA
2024 to 2026, regular season and playoffs) under the TBT rule: at the first
dead ball with under 4:00 left in the fourth quarter, the clock turns off and
the first team to reach the leading score plus 8 wins.

The true counterfactual is unobservable, because teams would play
differently without a clock, so the question is answered three ways: a
literal replay of the real play-by-play (a bound), an exact model of the race
to the target (a forecast, calibrated on real races inside games), and a
factual audit of the clock-driven endings the rule would remove.

Design, decisions, and data checks: `docs/design.md`. Data sources and
licenses: `DATA_SOURCES.md`. Family page:
https://ismayc.github.io/elam-ending-study/

<!-- terms -->
> **Terms used in this analysis.** Dotted-underlined terms anywhere below repeat these definitions on hover ([full glossary](https://github.com/ismayc/basketball-data-science/blob/main/docs/glossary.md)).
>
> *(no specialized metric terms in this document)*
<!-- /terms -->

## Results

<!-- gen:results -->
Coverage: 4,860 games, every regular-season game of NBA 2023-24 to 2025-26 and WNBA 2024 to 2026 plus every playoff game played (314 games, including 17 from the 2026 WNBA playoffs as of the last fetch). Each tier is computed in Python and again in R, and the two agree on every cell.

**Tier 1, literal replay.** Each game's real play-by-play, read under the Elam rule from the trigger on.

| League | Games | Winner changes | Neither team reaches the target |
|---|---|---|---|
| NBA regular season | 3,690 | 111 (3.0%) | 1,393 (38%) |
| NBA playoffs | 251 | 10 (4.0%) | 101 (40%) |
| WNBA regular season | 856 | 26 (3.0%) | 332 (39%) |
| WNBA playoffs | 63 | 3 (4.8%) | 31 (49%) |

A bound, not a forecast: the real teams played to the clock. Unresolved games are ones where the leader added fewer than 8 points before the buzzer.

**Tier 2, race to the target.** An exact model of the race from each game's trigger, built from clock-neutral points per possession. On 9,092 real races to leader + 8 in the second and third quarters it predicted 86.7% for the favorite against 86.2% observed (no bin off by more than 1.2 points; Brier 0.098 against 0.119 for a constant rate).

| League | Leader at the trigger wins, clock (real) | Leader wins, Elam (model) |
|---|---|---|
| NBA regular season | 90.7% | 90.6% |
| NBA playoffs | 88.2% | 90.4% |
| WNBA regular season | 90.0% | 89.2% |
| WNBA playoffs | 79.4% | 85.3% |

In the regular season the rule barely moves the leader's odds. The playoff rows rest on 308 games with a leader at the trigger, too few to read much into. The clearest shift is at big leads: NBA teams ahead by 11 to 15 at the trigger won 99.7% under the clock (95% interval 98.9% to 99.9%) against 98.4% in the model, since no clock runs out for them. By margin: `output/race_by_margin.csv`.

**Tier 3, the endgame audit.** What the clock does to real endings.

| League | Overtime | Free-throw share of points, last 4:00 + OT (Q1-Q3) | Games with a take foul by the trailing team, last 2:00 | Real minutes for the last 2:00, close games (others) |
|---|---|---|---|---|
| NBA regular season | 4.7% | 23% (14%) | 26% | 10.2 (4.6) |
| NBA playoffs | 5.2% | 25% (16%) | 29% | 11.5 (5.3) |
| WNBA regular season | 2.9% | 28% (17%) | 25% | 11.3 (5.0) |
| WNBA playoffs | 12.7% | 27% (17%) | 29% | 11.2 (5.6) |

Close games are within 5 points at 2:00 of Q4; minutes are medians of liveData wall-clock stamps. Elam would abolish the overtime and remove the clock that the take fouls and the long final minutes serve.
<!-- /gen:results -->

## Reproduce

```bash
python python/00_fetch_live.py      # liveData for playoff games (resumable)
python python/01_import.py          # events + checks against two other sources
python python/02_replay.py          # tier 1
python python/04_possessions.py     # points per possession
python python/05_race_model.py      # tier 2
python python/06_endgame_audit.py   # tier 3
python python/07_report.py          # this README's results
bash run_checks.sh                  # every gate, including the R reconcile
```

Raw play-by-play stays local (NBA.com terms); `output/` holds game-level
derived tables only.
