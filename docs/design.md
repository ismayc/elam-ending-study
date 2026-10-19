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

Road not taken: Monte Carlo simulation for tier 2. The family's Python and R
reconcile gate cannot pass with language-specific random streams, so tier 2
is an exact dynamic program over (points needed by each team, possession).

## Open definitions (to settle in the first script, then record here)

- **Dead-ball event set.** Proposed: fouls, timeouts, violations, turnovers,
  jump balls, and substitutions (which happen only at dead balls). A made
  field goal does not trigger, since play continues without a whistle; whether
  TBT counts it is unverified.
- **Trigger edge cases.** A game with no qualifying event under 4:00 triggers
  at the end of regulation. Events at exactly 4:00 do not count (strictly
  under).
- **Unresolved replays.** If neither team reaches the target before the real
  game ends (overtime included), the replay is "unresolved" and reported as
  its own category, never assigned a winner.
