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
   target first from each trigger state. Claim: how much Elam moves the
   leader's chance of winning, by margin at the trigger.
3. **Endgame audit.** Factual measures of the endgames Elam would remove:
   overtime, take fouls by the trailing team, the free-throw share of
   final-four-minute points, late decisions, and the real-clock length of the
   last two minutes.

## Decisions

Made by Chester Ismay on October 19, 2026, before any result was computed:

1. **Trigger:** the first dead ball with under 4:00 left in Q4 (TBT and CEBL
   style), in both leagues.
2. **Target:** leading score + 8 (the TBT rule). A tie at the trigger sets the
   target at the tied score + 8.
3. **Overtime games:** replayed from the Q4 trigger like every other game.
4. **Playoffs:** included. The NBA stats hosts did not answer from the
   machines used (October 19, 2026), so playoff rows come from the
   shufinskiy `nbastatsv3_po_*` archives (the same `PlayByPlayV3` rows), and
   the WNBA 2026 playoffs, absent from those archives, from the NBA's
   liveData feed (`events.parquet` carries a `feed` column). The 2026 WNBA
   Finals were still being played when the data was pulled.

## Definitions

- **Dead-ball event set** (`01_import.py`, `dead_ball` column): fouls,
  timeouts, violations, jump balls, substitutions (which happen only at dead
  balls), instant replays, ejections, and every turnover except "Bad Pass"
  and "Lost Ball", which are live-ball steals in both feeds (the
  out-of-bounds versions have their own subtypes). A made field goal does not
  trigger, since play continues without a whistle outside the last two
  minutes; whether TBT counts it is unverified. Turnovers come out 43% dead
  in V3 and 44% in liveData.
- **Trigger edge cases.** Events at exactly 4:00 do not count (strictly
  under). A game with no qualifying event under 4:00 triggers at the end of
  regulation; two blowouts did, with continuous play to the buzzer.
- **Unresolved replays.** If neither team reaches the target before the real
  game ends (overtime included), the replay is "unresolved" and reported as
  its own category, never assigned a winner.

## Tier 2 as built

`python/05_race_model.py`, mirrored in `R/05_race_model.R`. Possessions
alternate and score 0, 1, 2, 3, or 4+ points with clock-neutral
probabilities: Q1 to Q3 possessions starting with more than 60 seconds left,
Q4 possessions starting with more than 5:00 left, and not the first
possession of a period (`python/04_possessions.py`). Two versions:
league-season distributions for both teams, and team-adjusted (the offense's
and the opposing defense's distributions averaged). The ball at the trigger
goes to the team of the next shot, non-technical free throw, or turnover.
Playoff games use the regular-season distributions. Calibrated on 9,092
mid-game races (first dead ball under 6:00 of Q2 and Q3, target leader + 8),
because the NBA's real target-score games (All-Star exhibitions) are too few
and too unlike competitive play.

"Expected flips" (the sum over games of P(the real loser reaches the target
first)) treats the Elam ending as independent of the real one, so it is an
upper reference, not a forecast; the comparison that holds up is the
leader's win rate under the clock against the model's, by trigger margin
(`output/race_by_margin.csv`).

Road not taken: Monte Carlo simulation. The Python and R reconciliation
cannot pass with language-specific random streams, so tier 2 is an exact
dynamic program over (points needed by each team, possession).

## Data checks

Each check runs in `run_checks.sh`; each was shown to fail on an injected
error.

- **Final scores.** Every game's last play-by-play score must equal its
  LeagueGameLog final (4,860 of 4,860). Home and away are matched by team ID:
  a few neutral-site games list both teams with "@".
- **Endgame scores against a second feed.** The score at every clock instant
  from 5:00 of Q4 on is compared with the NBA liveData feed. Where they
  disagree, the game passes only if LeagueGameLog sides with V3 (two games,
  both liveData one point short).
- **Score stamps.** A forward fill of `PlayByPlayV3`'s score columns gives a
  wrong running score somewhere in about 6% of games. Three rules fix it,
  each pinned by a unit test: take scores only from made shots and free
  throws (Instant Replay rows carry a stale stamp); use a running maximum
  per team (free throws at one clock reading can be out of order); and let a
  scoring row set only its own team's score (a free-throw row can carry the
  other team's next score).
- **Possession scoring.** Points assigned to possessions must cover 99% of
  the points scored in their windows (99.4% to 99.5% here). The first
  possession of each period is left out: the possession builds often name the
  wrong offense there, crediting the other team's baskets.
- **Padding.** Some archive rows carry right-padded event types ("Foul" plus
  spaces), which would miss every exact match; they are stripped.
- **Wall clock.** The real time at a game-clock reading is the last action
  at or above it plus the game time that ran since. Spans shorter than the
  game time or longer than an hour are feed faults and are left empty (3
  games).
