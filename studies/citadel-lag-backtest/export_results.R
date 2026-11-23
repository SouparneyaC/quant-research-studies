# export_results.R
# Turns the saved R result objects into the small CSV tables kept in results/.
#
# The scripts that built the backtest objects (position returns, tenure segments,
# decay curves, factor data) were not saved. This script reads what they left behind
# and writes only quarter-level and summary tables, no position-level or vendor data.
#
# Usage: Rscript export_results.R <data_dir> <out_dir>
#   data_dir holds backtest_results.rds, lindy_backtest.rds, alpha_decay.rds,
#   factor_attribution.rds, all_firms_holdings.rds, prices_raw.rds

suppressMessages(library(dplyr))

args     <- commandArgs(trailingOnly = TRUE)
data_dir <- if (length(args) >= 1) args[1] else "data"
out_dir  <- if (length(args) >= 2) args[2] else "results"
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)
rd <- function(f) readRDS(file.path(data_dir, f))

bt    <- rd("backtest_results.rds")
lindy <- rd("lindy_backtest.rds")
decay <- rd("alpha_decay.rds")
fa    <- rd("factor_attribution.rds")
px    <- rd("prices_raw.rds")

spy <- px |> filter(symbol == "SPY") |> arrange(date)
spy_at <- function(d) tail(spy$adj_close[spy$date <= d], 1)
spy_ret <- function(a, b) mapply(function(x, y) spy_at(y) / spy_at(x) - 1, a, b)

# 1. Quarter-level returns of the three legs, SPY on three windows, and the factor data
q <- bt$portfolio_returns |>
  mutate(
    spy_ret_post_filing  = spy_ret,
    spy_ret_full_quarter = spy_ret(quarter_end_date, next_quarter_end),
    spy_ret_to_filing    = spy_ret(quarter_end_date, filing_date)
  ) |>
  select(-spy_ret, -spy_p_file, -spy_p_next)
f <- fa$regression_data |>
  select(quarter_end_date, Mkt_RF, SMB, HML, UMD, RF)
q <- left_join(q, f, by = "quarter_end_date")
write.csv(q, file.path(out_dir, "quarterly_returns.csv"), row.names = FALSE)

# 2. Tenure-segment summary and the saved factor regressions
write.csv(lindy$segment_perf_summary, file.path(out_dir, "segment_summary.csv"), row.names = FALSE)
write.csv(fa$regression_results, file.path(out_dir, "factor_regressions_saved.csv"), row.names = FALSE)

# 3. Decay curve: average over all positions at selected days after quarter end,
#    by quarter, with SPY over the same days
days <- c(1, 2, 5, 10, 20, 30, 45, 60, 90)
dq <- decay$decay_curves |>
  filter(day %in% days) |>
  group_by(quarter_end_date, day) |>
  summarise(mean_raw_return = mean(raw_return), n_positions = n(), .groups = "drop")
dq$spy_return <- mapply(function(d, k) spy_at(d + k) / spy_at(d) - 1,
                        dq$quarter_end_date, dq$day)
write.csv(dq, file.path(out_dir, "decay_by_quarter.csv"), row.names = FALSE)

# 4. Filing lag by firm, seven large filers, from the filing dates in the holdings tables.
#    A quarter whose filing is an amendment (13F-HR/A) carries the amendment's filing date,
#    so lags are also summarised over original filings only.
af <- rd("all_firms_holdings.rds") |>
  distinct(firm, quarter_end_date, disclosure_lag, submissionType) |>
  mutate(is_amendment = grepl("/A", submissionType))
lag_summary <- function(d) summarise(d, n_quarters = n(), mean_lag = round(mean(disclosure_lag), 1),
            median_lag = median(disclosure_lag), min_lag = min(disclosure_lag),
            max_lag = max(disclosure_lag), n_at_45 = sum(disclosure_lag == 45),
            n_over_45 = sum(disclosure_lag > 45))
all_q  <- af |> group_by(firm) |> lag_summary() |>
  left_join(af |> group_by(firm) |> summarise(n_amendment_quarters = sum(is_amendment)), by = "firm")
orig_q <- af |> filter(!is_amendment) |> group_by(firm) |> lag_summary() |>
  rename_with(~ paste0("orig_", .x), -firm)
write.csv(left_join(all_q, orig_q, by = "firm"),
          file.path(out_dir, "filing_lag_by_firm.csv"), row.names = FALSE)
cat("Wrote tables to", out_dir, "\n")
