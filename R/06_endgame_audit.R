# Tier 3, the endgame audit: the R implementation, written from the
# definitions in python/06_endgame_audit.py's docstring. python/03_reconcile.py
# compares the outputs.
#
# Run from the repo root:  Rscript R/06_endgame_audit.R

suppressPackageStartupMessages({
  library(dplyr)
  library(readr)
})

WALL_MAX <- 3600

events <- nanoparquet::read_parquet("data/events.parquet") |>
  select(gameId, seq, period, secs_left, actionType, subType, location, score_h, score_a)
games <- read_csv("output/games.csv", col_types = cols(gameId = col_character(),
                                                       .default = col_guess()))

last2 <- function(period, secs) period > 4 | (period == 4 & secs <= 120)
endgame <- function(period, secs) period > 4 | (period == 4 & secs <= 240)

takes <- events |>
  filter(subType == "Personal Take", last2(period, secs_left)) |>
  mutate(trailing = if_else(location == "h", score_h < score_a, score_a < score_h)) |>
  group_by(gameId) |>
  summarise(take_fouls_last2 = n(), take_fouls_trailing_last2 = sum(trailing),
            .groups = "drop")

sc <- events |>
  arrange(gameId, seq) |>
  group_by(gameId) |>
  mutate(dh = score_h - lag(score_h, default = 0L),
         da = score_a - lag(score_a, default = 0L)) |>
  ungroup() |>
  filter(dh > 0 | da > 0) |>
  mutate(pts = pmax(dh, da), is_ft = actionType == "Free Throw")

pts <- sc |>
  group_by(gameId) |>
  summarise(endgame_pts = sum(pts[endgame(period, secs_left)]),
            endgame_ft_pts = sum(pts[endgame(period, secs_left) & is_ft]),
            q1_q3_pts = sum(pts[period <= 3]),
            q1_q3_ft_pts = sum(pts[period <= 3 & is_ft]),
            last_score_ft = is_ft[which.max(seq)],
            .groups = "drop")

lead <- sc |>
  inner_join(games |> select(gameId, final_home, final_away, periods), by = "gameId",
             relationship = "many-to-one") |>
  mutate(w_lead = if_else(final_home > final_away, score_h - score_a, score_a - score_h)) |>
  arrange(gameId, seq) |>
  group_by(gameId) |>
  mutate(prev = lag(w_lead, default = 0L)) |>
  filter(w_lead > 0, prev <= 0) |>
  slice_max(seq, n = 1) |>
  ungroup() |>
  transmute(gameId, decided_late = period == periods & secs_left <= 60)

margin2 <- events |>
  filter(period == 4, secs_left >= 120) |>
  group_by(gameId) |>
  slice_max(seq, n = 1) |>
  ungroup() |>
  transmute(gameId, margin_at_2min = abs(score_h - score_a))

clock_secs <- function(clock) {
  m <- as.numeric(sub("^PT(\\d+)M.*$", "\\1", clock))
  s <- as.numeric(sub("^PT\\d+M([0-9.]+)S$", "\\1", clock))
  m * 60 + s
}
wall <- function(gid) {
  path <- if (substr(gid, 3, 3) == "2") {
    file.path("..", "playbyplay-study", "data", "pbpstats_live", "pbp",
              paste0("live_", gid, ".json"))
  } else file.path("data", "raw", "live", paste0(gid, ".json"))
  if (!file.exists(path)) return(c(NA_real_, NA_real_))
  a <- jsonlite::fromJSON(path, simplifyVector = TRUE)$game$actions
  t <- as.numeric(as.POSIXct(a$timeActual, format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC"))
  cs <- clock_secs(a$clock)
  at <- function(p, c) {
    i <- which(a$period == p & cs >= c)
    if (!length(i)) return(NA_real_)
    i <- max(i)
    t[i] + (cs[i] - c)
  }
  span <- function(s, e) {
    if (is.na(s) || is.na(e)) return(NA_real_)
    d <- round(e - s, 2)
    if (d >= 120 && d <= WALL_MAX) d else NA_real_
  }
  end_i <- which(a$period == 4 & a$actionType == "period" & a$subType == "end")
  end_t <- if (length(end_i)) t[end_i[1]] else NA_real_
  c(span(at(4, 120), end_t), span(at(3, 360), at(3, 240)))
}
w <- t(vapply(games$gameId, wall, numeric(2)))
walls <- tibble(gameId = games$gameId, real_secs_q4_last2 = w[, 1], real_secs_q3_mid2 = w[, 2])

pg <- games |>
  select(gameId, league, season, season_type, periods) |>
  mutate(overtime = periods > 4) |>
  left_join(margin2, by = "gameId", relationship = "one-to-one") |>
  left_join(takes, by = "gameId", relationship = "one-to-one") |>
  left_join(pts, by = "gameId", relationship = "one-to-one") |>
  left_join(lead, by = "gameId", relationship = "one-to-one") |>
  left_join(walls, by = "gameId", relationship = "one-to-one") |>
  mutate(take_fouls_last2 = coalesce(take_fouls_last2, 0L),
         take_fouls_trailing_last2 = coalesce(take_fouls_trailing_last2, 0L)) |>
  arrange(gameId)

med <- function(x) if (all(is.na(x))) NA_real_ else median(x, na.rm = TRUE)
summ_by <- function(frame, ...) {
  frame |>
    group_by(...) |>
    summarise(
      games = n(),
      overtime_rate = mean(overtime),
      take_fouls_per_game = mean(take_fouls_last2),
      games_with_trailing_take = mean(take_fouls_trailing_last2 > 0),
      endgame_ft_share = sum(endgame_ft_pts) / sum(endgame_pts),
      q1_q3_ft_share = sum(q1_q3_ft_pts) / sum(q1_q3_pts),
      last_score_ft_rate = mean(last_score_ft),
      decided_late_rate = mean(decided_late),
      wall_games = sum(!is.na(real_secs_q4_last2)),
      median_real_min_q4_last2 = med(real_secs_q4_last2) / 60,
      close_games = sum(margin_at_2min <= 5),
      median_real_min_q4_last2_close = med(real_secs_q4_last2[margin_at_2min <= 5]) / 60,
      median_real_min_q4_last2_not_close = med(real_secs_q4_last2[margin_at_2min > 5]) / 60,
      median_real_min_q3_mid2 = med(real_secs_q3_mid2) / 60,
      .groups = "drop")
}
summ <- bind_rows(summ_by(pg, league, season, season_type),
                  summ_by(pg, league, season_type) |> mutate(season = "pooled"),
                  summ_by(pg, league) |> mutate(season = "pooled", season_type = "all"))

write_csv(pg |> select(gameId, overtime, margin_at_2min, take_fouls_last2,
                       take_fouls_trailing_last2, endgame_pts, endgame_ft_pts, q1_q3_pts,
                       q1_q3_ft_pts, last_score_ft, decided_late, real_secs_q4_last2,
                       real_secs_q3_mid2), "output/endgame_games_r.csv", na = "")
write_csv(summ, "output/endgame_summary_r.csv", na = "")
cat("wrote output/endgame_games_r.csv and output/endgame_summary_r.csv\n")
