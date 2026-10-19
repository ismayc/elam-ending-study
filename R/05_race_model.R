# Tier 2, race to target: the R implementation, written from the model in
# python/05_race_model.py's docstring. python/03_reconcile.py compares the
# outputs cell by cell.
#
# State (home need, away need, ball). With x = P(home wins | home ball) and
# y = P(home wins | away ball):
#   x = pH0 * y + C,  y = pA0 * x + B   =>   x = (pH0 * B + C) / (1 - pH0 * pA0)
#
# Run from the repo root:  Rscript R/05_race_model.R

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
})

K <- 5L
TARGET_MARGIN <- 8L
CALIB_SECS <- 360

events <- nanoparquet::read_parquet("data/events.parquet") |>
  select(gameId, seq, period, secs_left, actionType, description, location, dead_ball,
         score_h, score_a)
games <- read_csv("output/games.csv", col_types = cols(gameId = col_character(),
                  home_team_id = col_character(), away_team_id = col_character(),
                  .default = col_guess()))
replay <- read_csv("output/replay_games.csv", col_types = cols(gameId = col_character(),
                   .default = col_guess()))
dist <- read_csv("output/ppp_distributions.csv", col_types = cols(team_id = col_character(),
                 .default = col_guess()))

probs <- function(d) as.numeric(d[paste0("p", 0:4)])
key <- function(...) paste(..., sep = "|")
lg <- list(); off <- list(); dfn <- list()
for (i in seq_len(nrow(dist))) {
  r <- dist[i, ]
  if (r$scope == "league") lg[[key(r$league, r$season)]] <- probs(r)
  if (r$scope == "offense") off[[key(r$league, r$season, r$team_id)]] <- probs(r)
  if (r$scope == "defense") dfn[[key(r$league, r$season, r$team_id)]] <- probs(r)
}

memos <- new.env()

race <- function(nh, na, home_ball, ph, pa, memo_key) {
  if (is.null(memos[[memo_key]])) memos[[memo_key]] <- new.env()
  m <- memos[[memo_key]]
  sk <- function(h, a) paste(h, a)
  if (is.null(m[[sk(nh, na)]])) {
    for (total in 2:(nh + na)) {
      for (h in max(1, total - na):min(nh, total - 1)) {
        a <- total - h
        if (!is.null(m[[sk(h, a)]])) next
        cc <- 0; bb <- 0
        for (k in 1:(K - 1)) {
          cc <- cc + ph[k + 1] * (if (k >= h) 1 else m[[sk(h - k, a)]][2])
          bb <- bb + pa[k + 1] * (if (k >= a) 0 else m[[sk(h, a - k)]][1])
        }
        x <- (ph[1] * bb + cc) / (1 - ph[1] * pa[1])
        y <- pa[1] * x + bb
        m[[sk(h, a)]] <- c(x, y)
      }
    }
  }
  v <- m[[sk(nh, na)]]
  if (home_ball) v[1] else v[2]
}

ball_after <- function(ev, starts) {
  cand <- ev |>
    filter(location %in% c("h", "v"),
           actionType %in% c("Made Shot", "Missed Shot", "Turnover") |
             (actionType == "Free Throw" & !grepl("technical", tolower(description)))) |>
    select(gameId, seq, location)
  starts |>
    inner_join(cand, by = "gameId", relationship = "many-to-many") |>
    filter(seq > start_seq) |>
    arrange(gameId, start_seq, seq) |>
    group_by(gameId, start_seq) |>
    summarise(ball = first(location), .groups = "drop")
}

solve_states <- function(states) {
  n <- nrow(states)
  target <- integer(n); p_league <- numeric(n); p_team <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    r <- states[i, ]
    target[i] <- max(r$score_h, r$score_a) + TARGET_MARGIN
    nh <- target[i] - r$score_h; na <- target[i] - r$score_a
    hb <- r$ball == "h"
    L <- lg[[key(r$league, r$season)]]
    p_league[i] <- race(nh, na, hb, L, L, key("L", r$league, r$season))
    kh <- key(r$league, r$season, r$home_team_id); ka <- key(r$league, r$season, r$away_team_id)
    if (!is.null(off[[kh]]) && !is.null(off[[ka]])) {
      ph <- (off[[kh]] + dfn[[ka]]) / 2
      pa <- (off[[ka]] + dfn[[kh]]) / 2
      p_team[i] <- race(nh, na, hb, ph, pa, key("T", r$league, r$season, r$home_team_id,
                                              r$away_team_id))
    }
  }
  states |> mutate(target = target, p_home_league = p_league, p_home_team = p_team)
}

# Games: from each replay trigger.
trig <- replay |> transmute(gameId, start_seq = trigger_seq, score_h = trigger_h,
                            score_a = trigger_a)
states <- trig |>
  left_join(ball_after(events, trig), by = c("gameId", "start_seq"),
            relationship = "one-to-one") |>
  inner_join(games |> select(gameId, league, season, season_type, home_team_id,
                             away_team_id), by = "gameId", relationship = "one-to-one") |>
  mutate(ball = coalesce(ball, "h"))
rg <- solve_states(states) |>
  inner_join(replay |> select(gameId, actual_winner, trigger_margin, trigger_leader),
             by = "gameId", relationship = "one-to-one") |>
  mutate(p_actual_league = if_else(actual_winner == "home", p_home_league, 1 - p_home_league),
         p_actual_team = if_else(actual_winner == "home", p_home_team, 1 - p_home_team),
         p_leader_league = case_when(trigger_leader == "home" ~ p_home_league,
                                     trigger_leader == "away" ~ 1 - p_home_league,
                                     TRUE ~ NA_real_)) |>
  arrange(gameId)

summ_by <- function(frame, ...) {
  frame |>
    group_by(...) |>
    summarise(games = n(),
              expected_flips_league = sum(1 - p_actual_league),
              expected_flips_team = sum(1 - p_actual_team),
              led_games = sum(trigger_leader != "tied"),
              leader_won_clock = sum(trigger_leader != "tied" & trigger_leader == actual_winner),
              leader_wins_elam_league = sum(p_leader_league, na.rm = TRUE),
              .groups = "drop") |>
    mutate(expected_flip_rate_league = expected_flips_league / games,
           expected_flip_rate_team = expected_flips_team / games,
           leader_win_rate_clock = leader_won_clock / led_games,
           leader_win_rate_elam_league = leader_wins_elam_league / led_games)
}
summ <- bind_rows(summ_by(rg, league, season, season_type),
                  summ_by(rg, league, season_type) |> mutate(season = "pooled"),
                  summ_by(rg, league) |> mutate(season = "pooled", season_type = "all"))

labels <- c("1", "2", "3", "4", "5", "6", "7-8", "9-10", "11-15", "16+")
z <- 1.96
marg <- rg |>
  filter(trigger_leader != "tied") |>
  mutate(margin = as.character(cut(trigger_margin, c(-Inf, 1, 2, 3, 4, 5, 6, 8, 10, 15, Inf),
                                   labels = labels)),
         won = as.numeric(trigger_leader == actual_winner),
         p_leader_team = if_else(trigger_leader == "home", p_home_team, 1 - p_home_team)) |>
  group_by(league, margin) |>
  summarise(games = n(), clock = mean(won), elam_league = mean(p_leader_league),
            elam_team = mean(p_leader_team), .groups = "drop") |>
  mutate(centre = (clock + z^2 / (2 * games)) / (1 + z^2 / games),
         half = z * sqrt(clock * (1 - clock) / games + z^2 / (4 * games^2)) / (1 + z^2 / games),
         clock_lo = centre - half, clock_hi = centre + half,
         elam_minus_clock = elam_league - clock) |>
  select(-centre, -half)

# Calibration races: first dead ball under 6:00 of Q2 and Q3, regular season.
reg <- games |> filter(season_type == "regular") |>
  select(gameId, league, season, home_team_id, away_team_id)
ev <- events |> filter(gameId %in% reg$gameId)
start <- ev |>
  filter(period %in% c(2L, 3L), dead_ball, secs_left < CALIB_SECS) |>
  arrange(gameId, period, seq) |>
  group_by(gameId, period) |>
  slice_head(n = 1) |>
  ungroup() |>
  transmute(gameId, race_period = period, start_seq = seq, score_h, score_a)
cstates <- start |>
  left_join(ball_after(ev, start |> select(gameId, start_seq)),
            by = c("gameId", "start_seq"), relationship = "one-to-one") |>
  inner_join(reg, by = "gameId", relationship = "many-to-one") |>
  filter(!is.na(ball))
csolved <- solve_states(cstates)
outcome <- ev |>
  inner_join(csolved |> select(gameId, race_period, start_seq, target), by = "gameId",
             relationship = "many-to-many") |>
  filter(seq > start_seq, score_h >= target | score_a >= target) |>
  arrange(gameId, race_period, seq) |>
  group_by(gameId, race_period) |>
  summarise(home_first = as.integer(first(score_h >= target)), .groups = "drop")
cr <- csolved |> inner_join(outcome, by = c("gameId", "race_period"),
                            relationship = "one-to-one")

cal <- bind_rows(lapply(c("league", "team"), function(v) {
  p <- cr[[paste0("p_home_", v)]]
  d <- cr[!is.na(p), ]; p <- p[!is.na(p)]
  fav_home <- p >= 0.5
  p_fav <- ifelse(fav_home, p, 1 - p)
  fav_first <- ifelse(fav_home, d$home_first, 1 - d$home_first)
  b <- cut(p_fav, c(0.5, 0.6, 0.7, 0.8, 0.9, 0.95, Inf), right = FALSE,
           labels = c("[0.5, 0.6)", "[0.6, 0.7)", "[0.7, 0.8)", "[0.8, 0.9)",
                      "[0.9, 0.95)", "[0.95, inf)"))
  bins <- tibble(bin = as.character(b), p_fav, fav_first) |>
    group_by(bin) |>
    summarise(races = n(), mean_predicted = mean(p_fav), observed = mean(fav_first),
              .groups = "drop")
  base <- mean(fav_first)
  bind_rows(bins,
            tibble(bin = "all", races = length(p_fav), mean_predicted = mean(p_fav),
                   observed = base),
            tibble(bin = "brier", races = length(p_fav),
                   mean_predicted = mean((p_fav - fav_first)^2),
                   observed = mean((base - fav_first)^2))) |>
    mutate(version = v)
}))

write_csv(rg |> select(gameId, ball, target, p_home_league, p_home_team, p_actual_league,
                       p_leader_league), "output/race_games_r.csv", na = "")
write_csv(summ, "output/race_summary_r.csv", na = "")
write_csv(marg, "output/race_by_margin_r.csv", na = "")
write_csv(cal, "output/race_calibration_r.csv", na = "")
cat("wrote output/race_*_r.csv\n")
