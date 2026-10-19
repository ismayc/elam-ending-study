# Tier 1, literal replay: the R implementation, written independently of
# python/02_replay.py from the rule in docs/design.md. python/03_reconcile.py
# compares the two outputs cell by cell.
#
# Rule: the trigger is the first dead ball with strictly under 4:00 left in
# Q4 (a game with none triggers at its last Q4 event); the target is the
# leading score at the trigger plus 8; from the trigger on, the first team to
# reach the target wins; if neither does before the real game ends, the game
# is unresolved.
#
# Run from the repo root:  Rscript R/02_replay.R

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
})

events <- nanoparquet::read_parquet("data/events.parquet") |>
  select(gameId, seq, period, secs_left, actionType, dead_ball, score_h, score_a)
games <- read_csv("output/games.csv", col_types = cols(gameId = col_character(),
                                                       .default = col_guess()))

q4 <- events |> filter(period == 4) |> arrange(gameId, seq)

dead <- q4 |>
  filter(dead_ball, secs_left < 240) |>
  group_by(gameId) |>
  slice_head(n = 1) |>
  ungroup() |>
  mutate(trigger_kind = "dead ball")

fallback <- q4 |>
  filter(!gameId %in% dead$gameId) |>
  group_by(gameId) |>
  slice_tail(n = 1) |>
  ungroup() |>
  mutate(trigger_kind = "end of regulation")

trig <- bind_rows(dead, fallback) |>
  transmute(gameId, trigger_seq = seq, trigger_secs_left = secs_left,
            trigger_action = actionType, trigger_h = score_h, trigger_a = score_a,
            trigger_kind, target = pmax(score_h, score_a) + 8L)

reach <- events |>
  inner_join(trig |> select(gameId, trigger_seq, target), by = "gameId",
             relationship = "many-to-one") |>
  filter(seq > trigger_seq, score_h >= target | score_a >= target) |>
  arrange(gameId, seq) |>
  group_by(gameId) |>
  slice_head(n = 1) |>
  ungroup() |>
  transmute(gameId, reach_seq = seq, reach_period = period, reach_secs_left = secs_left,
            elam_winner = if_else(score_h >= target, "home", "away"),
            reach_h = score_h, reach_a = score_a)

rep <- games |>
  select(gameId, league, season, season_type, final_home, final_away, periods) |>
  left_join(trig, by = "gameId", relationship = "one-to-one") |>
  left_join(reach, by = "gameId", relationship = "one-to-one") |>
  mutate(
    actual_winner = if_else(final_home > final_away, "home", "away"),
    elam_winner = coalesce(elam_winner, "unresolved"),
    trigger_margin = abs(trigger_h - trigger_a),
    trigger_leader = case_when(trigger_h > trigger_a ~ "home",
                               trigger_h < trigger_a ~ "away",
                               TRUE ~ "tied"),
    overtime = periods > 4,
    flipped = elam_winner != "unresolved" & elam_winner != actual_winner
  ) |>
  arrange(gameId)

summarize_by <- function(frame, ...) {
  frame |>
    group_by(...) |>
    # overtime_flipped and overtime_games come before flipped and overtime are
    # summed: summarise() masks a column with its own aggregate for every
    # later argument (memory: dplyr-summarise-sequential-masking), and in the
    # first draft overtime_flipped read the summed flipped and equaled the
    # overtime game count. 03_reconcile.py caught it.
    summarise(
      games = n(),
      trigger_dead_ball = sum(trigger_kind == "dead ball"),
      unresolved = sum(elam_winner == "unresolved"),
      overtime_resolved = sum(overtime & elam_winner != "unresolved"),
      overtime_flipped = sum(overtime & flipped),
      flipped = sum(flipped),
      overtime_games = sum(overtime),
      leader_wins_actual = sum(trigger_leader == actual_winner),
      leader_wins_elam = sum(trigger_leader == elam_winner),
      tied_at_trigger = sum(trigger_leader == "tied"),
      reached_in_ot = sum(!is.na(reach_period) & reach_period > 4),
      .groups = "drop"
    ) |>
    mutate(flip_rate = flipped / games, unresolved_rate = unresolved / games)
}

summ <- bind_rows(
  summarize_by(rep, league, season, season_type),
  summarize_by(rep, league, season_type) |> mutate(season = "pooled"),
  summarize_by(rep, league) |> mutate(season = "pooled", season_type = "all")
) |>
  arrange(league, season, season_type)

write_csv(rep |> select(gameId, trigger_seq, trigger_secs_left, trigger_kind, trigger_h,
                        trigger_a, target, reach_seq, reach_period, reach_secs_left,
                        reach_h, reach_a, elam_winner, actual_winner, flipped),
          "output/replay_games_r.csv", na = "")
write_csv(summ, "output/replay_summary_r.csv", na = "")
cat("wrote output/replay_games_r.csv and output/replay_summary_r.csv\n")
