# Design

## Question

How would the Elam Ending have changed NBA and WNBA results over the last
three seasons? The true counterfactual is unobservable, because endgame
behavior changes once the clock turns off, so the study answers it in three
tiers, each with its own honest claim.

1. **Literal replay.** Walk each game's real play-by-play from the trigger and
   record which team reaches the target first. Claim: "under literal replay,
   X% of games flip." A bound, not a counterfactual.
2. **Race to target.** Possession-level scoring distributions from
   clock-neutral play, then the exact probability that each team reaches the
   target first from each trigger state. Claim: "Elam moves a trailing team's
   win probability from A% to B%; about Y expected flips a season."
3. **Pathology audit.** Factual measures of the endgames Elam would remove:
   intentional-foul sequences and their real-clock length, the free-throw
   share of final-four-minute points, overtime frequency, and the share of
   games that end on a made basket.

## Decisions

Decided by Chester on October 19, 2026 (recorded in
`~/.claude/open-questions.md`):

1. **Trigger:** the first dead ball with under 4:00 left in Q4 (TBT and CEBL
   style), in both leagues.
2. **Target:** leading score + 8 (the TBT rule). A tie at the trigger sets the
   target at the tied score + 8.
3. **Overtime games:** replayed from the Q4 trigger like every other game.
4. **Playoffs:** included, harvested first. The NBA stats hosts were blocked
   from both machines on October 19, 2026, so the playoff rows come from the
   shufinskiy `nbastatsv3_po_*` archives (same `PlayByPlayV3` rows). WNBA 2026
   playoffs are not in the archive yet.

Tier 2 as built (`python/05_race_model.py`, mirrored in `R/05_race_model.R`):
possessions alternate and score 0, 1, 2, 3, or 4+ points with clock-neutral
probabilities (Q1 to Q3 possessions starting with more than 60 seconds left,
Q4 possessions starting with more than 5:00 left, period-start possessions
excluded; `python/04_possessions.py`). Two versions: league-season
distributions for both teams, and team-adjusted (offense's and opponent
defense's distributions averaged). The ball at the trigger goes to the team
of the next shot, non-technical free throw, or turnover. Playoff games use
the regular-season distributions. Calibrated on 9,092 mid-game races (first
dead ball under 6:00 of Q2 and Q3, target leader + 8).

"Expected flips" (the sum over games of P(the real loser reaches the target
first)) treats the Elam ending as independent of the real one, so it is an
upper reference, not a forecast; the comparison that holds up is the
leader's win rate under the clock against the model's, by trigger margin
(`output/race_by_margin.csv`).

Road not taken: Monte Carlo simulation for tier 2. The family's Python and R
reconcile gate cannot pass with language-specific random streams, so tier 2
is an exact dynamic program over (points needed by each team, possession).

4a. **WNBA 2026 playoffs** come from the liveData feed (no V3 source was
   reachable), so `events.parquet` carries a `feed` column. Partial until the
   2026 Finals end.

## Definitions

- **Dead-ball event set** (`01_import.py`, `dead_ball` column): fouls,
  timeouts, violations, jump balls, substitutions (which happen only at dead
  balls), instant replays, ejections, and every turnover except "Bad Pass"
  and "Lost Ball", which are live-ball steals in both feeds (the
  out-of-bounds versions have their own subtypes). A made field goal does not
  trigger, since play continues without a whistle outside the last two
  minutes; whether TBT counts it is unverified. Turnovers come out 43% dead
  in V3 and 44% in liveData.

## Open definitions (to settle in the replay script, then record here)

- **Trigger edge cases.** A game with no qualifying event under 4:00 triggers
  at the end of regulation. Events at exactly 4:00 do not count (strictly
  under).
- **Unresolved replays.** If neither team reaches the target before the real
  game ends (overtime included), the replay is "unresolved" and reported as
  its own category, never assigned a winner.
