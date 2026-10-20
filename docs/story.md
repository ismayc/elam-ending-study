# What if the NBA and WNBA used the Elam Ending?

The Elam Ending turns the game clock off near the end and plays to a target
score instead. The Basketball Tournament (TBT) version used here switches on
at the first dead ball with under four minutes left in the fourth quarter,
and the first team to reach the leading score plus 8 wins. This study asks
what that rule would have done to the last three seasons of both leagues:
4,860 games, every regular-season and playoff game of NBA 2023-24 to 2025-26
and WNBA 2024 to 2026. The short answer: it would change the winner of a few
close games, barely move the odds of the team ahead, and cut the slowest
minutes in basketball.

<div class="tiles">
<div class="tile"><div class="label">Winners changed</div>
<div class="value">3.0%</div>
<div class="sub">NBA regular-season games whose real play-by-play, read under the rule, crowns the other team (111 of 3,690).</div></div>
<div class="tile"><div class="label">Leader's odds</div>
<div class="value">90.7 vs 90.6</div>
<div class="sub">Percent of NBA regular-season games won by the team ahead at the trigger: real games against the race model.</div></div>
<div class="tile"><div class="label">Model check</div>
<div class="value">9,092</div>
<div class="sub">Real races to leader + 8 inside games; the model is within 1.3 points of the observed rate everywhere.</div></div>
<div class="tile"><div class="label">Close-game endings</div>
<div class="value">10.2 min</div>
<div class="sub">Median real minutes for the last 2:00 of an NBA game within 5 points, against 4.6 otherwise.</div></div>
</div>

<div class="eyebrow beat">The question</div>

## Three ways to answer something unobservable

Nobody knows exactly how these games would have gone without a clock,
because teams play the end of a game to the clock: they foul to stop it,
hold for the last shot, and call timeouts to set up a play. So the question
gets three answers, each with an honest claim attached.

The first is a literal replay. Each game's real play-by-play is read from
the trigger on, and the first team whose real score reaches the target wins.
That keeps every clock-driven decision the teams actually made, so it is a
bound, not a forecast.

The second is a model of the race to the target. From the score and
possession at the trigger, it computes the exact chance that each team gets
there first, using how often possessions score 0, 1, 2, 3, or 4 points when
nobody is playing to the clock. Before it is used on endings, it is checked
against real races to "leader + 8" that happen inside games, in the second
and third quarters.

The third is an audit of the endings the rule would remove: overtime, fouls
to stop the clock, the free-throw share of late points, and how long the
last two minutes really take.

{{svg:dg2_three_answers|How the NBA regular season's games flow through the three answers; each band's width is a count of games. The literal replay decides most games and leaves the rest open. Every game, decided or open, flows on to the race model, which was checked first on real races inside games. The audit sits alongside and measures what the clock adds after the trigger.}}

Every result was computed twice, in Python and in R, and the two agree on
every cell. Final scores were checked against the league's game logs (all
4,860 match) and late-game scores against a second play-by-play feed.

<div class="eyebrow beat">Literal replay</div>

## A few close games change hands

The replay stops each game the moment a team reaches the target, so a
real comeback after that moment no longer counts. The game with the latest
such finish shows how that changes a winner: the Lakers reached the target
first, and the Bulls won the real game at the buzzer.

{{svg:dg1_one_game|One real game read under the rule. At the trigger the Lakers led, which set the target. They reached it first, so the Elam game ends there with the Lakers winning; the seconds the Bulls used to win the real game are never played. The game is picked by rule: the NBA regular-season flip with the latest finish.}}

Under a literal replay, 3.0% of NBA regular-season games and 3.0% of WNBA
regular-season games crown the other team. Most of them were close at the
trigger: 16% of NBA games tied at the trigger change winner, and no
game with a lead of more than 15 does.

{{fig:fig1_replay_margin_py|Share of games whose winner changes under a literal replay, by the margin at the trigger. Close games change hands most often; no NBA or WNBA game led by more than 15 does.}}

The replay cannot decide every game. In 38% of NBA regular-season games
neither team reaches the target before the real final buzzer. Those games
are mostly lopsided: 57% of NBA games led by 16 or more at the trigger end
that way, against 13% of one-point games. The race model below covers them.

<div class="eyebrow beat">Race to the target</div>

## The team ahead keeps almost exactly its odds

The race model reads the same game from its trigger state instead of from
what happened next. It made the Lakers clear favorites to reach the target
first, and in the replay they did.

{{svg:dg3_race_step|One step of the race model, on the same game. Each possession scores 0 to 4 points with the shares shown, measured on possessions where nobody plays to the clock. From the trigger, the Bulls' possession leads to one of five states; repeating that step from every state until one team reaches the target gives the exact chance each team gets there first.}}

On the 9,092 real mid-game races, the model said the favorite would get
there first 86.8% of the time; it did 86.2% of the time. No range of
predictions was off by more than 1.3 points, and its Brier score was 0.098,
against 0.119 for always guessing the overall rate.

{{fig:fig3_calibration_py|Predicted against observed on 9,092 real races to leader + 8 in the second and third quarters. Points on the dashed line would be perfect; every bin is within 1.3 points of it.}}

Applied to the endings, it says the rule would barely change how often the
team ahead at the trigger wins: 90.7% of NBA regular-season games under the
clock, 90.6% under Elam, and 90.0% against 89.3% in the WNBA. The clearest
shift is at big leads. NBA teams up 11 to 15 won 99.7% of real games, with
a 95% interval of 98.9% to 99.9%, and the model gives them 98.4%: with no
clock to run out, a trailing team always gets one more chance.

{{fig:fig2_leader_margin_py|How often the team ahead at the trigger wins, by margin. Dots are real games with 95% intervals; lines are the race model's Elam forecast. The model falls outside the interval in one of the 20 bins, NBA leads of 11 to 15, about what chance alone would give.}}

The playoffs show bigger gaps, but they rest on 308 games with a leader at
the trigger, too few to read much into.

<div class="eyebrow beat">The endings it would remove</div>

## The slowest minutes in basketball

The clock shapes the end of a real game in ways the rule would remove.

| | Overtime | Free-throw share of points, last 4:00 and overtime (Q1-Q3) | Trailing team commits a take foul, last 2:00 | Real minutes for the last 2:00, close games (others) |
|---|---|---|---|---|
| NBA regular season | 4.7% | 23% (14%) | 26% of games | 10.2 (4.6) |
| WNBA regular season | 2.9% | 28% (17%) | 25% of games | 11.3 (5.0) |

Free throws make up 23% of NBA points in the last four minutes and
overtime, against 14% in the first three quarters. A trailing team commits a
take foul, a deliberate foul to stop the clock, in the last two minutes of
26% of NBA games. And the last two minutes of a close NBA game take a median
of 10.2 real minutes, more than twice the 4.6 of other games; NBA games
separated by more than 20 at 2:00 take 3.5.

{{fig:fig4_minutes_margin_py|Median real minutes for the last two minutes of the fourth quarter, by the margin with 2:00 left. The dashed line is a neutral two minutes (the third quarter from 6:00 to 4:00); the solid line is two minutes of game time.}}

<div class="eyebrow beat">Limits</div>

## What this does not show

The literal replay keeps the clock strategy the real teams used, and the
race model assumes possessions score the way they do when nobody watches
the clock. Real Elam endings would sit somewhere else: teams would stop
fouling and holding, and might shoot differently with a target in sight.
The model also treats each possession as independent and gives each team its
league's or its own season's scoring rates, with no adjustment for who is on
the floor. The NBA's real target-score games are All-Star exhibitions, too
few and too unlike competitive play to test it on. And the 2026 WNBA Finals
were still being played when the data was pulled.
