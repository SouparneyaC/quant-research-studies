# 02_analysis.R
# Pull position-level 13F data for target institutions. Computes position turnover metrics per fund per quarter and Compares deadline huggers vs early filers.
# Run 01_load_and_build.R first
# Please note: QKIDs are hardcoded to avoid interactive qk_search_mgr(). This makes the script fully reproducible and pipeline-safe.

library(qkiosk)
library(dplyr)

# Checks dependencies from script 01
if (!exists("consistency")) {
  stop("Run 01_load_and_build.R first.")
}

# HARDCODED QKIDs
# These were resolved once via qk_search_mgr() and hardcoded here for reproducibility. No interactive prompts required.
# What I do to resolve a new QKID interactively:
#   1. qk_search_mgr("fund name")  # run alone, make selection, copy QKID
#   2. then hardcode below

# DEADLINE HUGGERS
sus       <- qk_cik(1446194)   # SUSQUEHANNA INTERNATIONAL GROUP LLP
parallax  <- qk_cik(1521001)   # PARALLAX VOLATILITY ADVISERS L.P.
wolverine <- qk_cik(927337)    # WOLVERINE TRADING LLC

# EARLY FILERS (control group)
baillie   <- qk_cik(1088875)   # BAILLIE GIFFORD & CO
swiss     <- qk_cik(1582202)   # SWISS NATIONAL BANK

cat("QKIDs loaded:\n")
cat("  SIG:      ", as.character(sus), "\n")
cat("  Parallax: ", as.character(parallax), "\n")
cat("  Wolverine:", as.character(wolverine), "\n")
cat("  Baillie:  ", as.character(baillie), "\n")
cat("  Swiss:    ", as.character(swiss), "\n")

# PULLS POSITION-LEVEL 13F DATA
# 8 quarters ending 2025Q1 = 2023Q2 through 2025Q1
# agg=FALSE gives submanager-level detail: QK's key data advantage
# NOTE this will use API creds

cat("\nPulling position data...\n")

sig_sus   <- qk_institutional(sus,       yyyyqq = 202501, qtrs = 8, agg = FALSE)
sig_par   <- qk_institutional(parallax,  yyyyqq = 202501, qtrs = 8, agg = FALSE)
sig_wol   <- qk_institutional(wolverine, yyyyqq = 202501, qtrs = 8, agg = FALSE)
sig_bail  <- qk_institutional(baillie,   yyyyqq = 202501, qtrs = 8, agg = FALSE)
sig_swiss <- qk_institutional(swiss,     yyyyqq = 202501, qtrs = 8, agg = FALSE)

# CONVERTS AND TAG
df_sus   <- to_df(sig_sus)
df_par   <- to_df(sig_par)
df_wol   <- to_df(sig_wol)
df_bail  <- to_df(sig_bail)
df_swiss <- to_df(sig_swiss)

cat("\nRow counts:\n")
cat("  SIG:      ", nrow(df_sus),   "\n")
cat("  Parallax: ", nrow(df_par),   "\n")
cat("  Wolverine:", nrow(df_wol),   "\n")
cat("  Baillie:  ", nrow(df_bail),  "\n")
cat("  Swiss:    ", nrow(df_swiss), "\n")

# Tag with fund identity and behavioral type
df_sus$fund    <- "SIG";       df_sus$type    <- "deadline_hugger"
df_par$fund    <- "Parallax";  df_par$type    <- "deadline_hugger"
df_wol$fund    <- "Wolverine"; df_wol$type    <- "deadline_hugger"
df_bail$fund   <- "Baillie";   df_bail$type   <- "early_filer"
df_swiss$fund  <- "Swiss";     df_swiss$type  <- "early_filer"

# Fix type mismatch in otherManager before combining
df_sus$otherManager   <- as.character(df_sus$otherManager)
df_par$otherManager   <- as.character(df_par$otherManager)
df_wol$otherManager   <- as.character(df_wol$otherManager)
df_bail$otherManager  <- as.character(df_bail$otherManager)
df_swiss$otherManager <- as.character(df_swiss$otherManager)

all_funds <- bind_rows(df_sus, df_par, df_wol, df_bail, df_swiss)
cat("\nCombined rows:", nrow(all_funds), "\n")

# 4. COMPUTE FILING LAG PER ROW
all_funds$lag <- as.numeric(
  as.Date(as.character(all_funds$filedDate),    "%Y%m%d") -
    as.Date(as.character(all_funds$reportPeriod), "%Y%m%d")
)

# COMPUTES TURNOVER METRICS PER FUND PER QUARTER
# turnover_pct   = (new + deleted positions) / total positions
# value_turnover = sum(|QOQ value change|) / total portfolio value
# opt_pct        = options positions / total positions
# ------------------------------------------------------------------------------
turnover <- all_funds %>%
  group_by(fund, type, reportPeriod, lag) %>%
  summarise(
    total_positions = n(),
    new_positions   = sum(newOrDel == "NEW",             na.rm = TRUE),
    del_positions   = sum(newOrDel == "DEL",             na.rm = TRUE),
    turnover_pct    = (new_positions + del_positions) / total_positions,
    abs_qoq_value   = sum(abs(QOQValue),                 na.rm = TRUE),
    total_value     = sum(abs(value),                    na.rm = TRUE),
    value_turnover  = abs_qoq_value / total_value,
    opt_positions   = sum(putCall %in% c("CALL", "PUT"), na.rm = TRUE),
    opt_pct         = opt_positions / total_positions,
    .groups = "drop"
  )

cat("\n--- Turnover by Fund and Quarter ---\n")
print(turnover[, c("fund", "type", "reportPeriod", "lag",
                   "turnover_pct", "value_turnover", "opt_pct")])

# SUMMARY TABLE
turnover_summary <- turnover %>%
  group_by(type) %>%
  summarise(
    avg_lag          = mean(lag,            na.rm = TRUE),
    avg_turnover_pct = mean(turnover_pct,   na.rm = TRUE),
    avg_value_turn   = mean(value_turnover, na.rm = TRUE),
    avg_opt_pct      = mean(opt_pct,        na.rm = TRUE),
    n_fund_quarters  = n(),
    .groups = "drop"
  )

cat("\n=== CORE RESULT ===\n")
print(turnover_summary)

cat("\nTurnover ratio (huggers / early):",
    round(
      turnover_summary$avg_turnover_pct[turnover_summary$type == "deadline_hugger"] /
        turnover_summary$avg_turnover_pct[turnover_summary$type == "early_filer"],
      2), "x\n")

# Simplex Trading - high optpct (0.79) but files EARLY (avg lag ~24 days)
# Controlled exception: Will investigate this as a footnote in paper either different regulatory regime or different strategic calculus
cat("\n--- Simplex Trading: Controlled Exception ---\n")
simplex_check <- consistency %>%
  filter(grepl("SIMPLEX", name, ignore.case = TRUE))
print(simplex_check)

# FOR PYTHON VISUALIZATION (Optional)
write.csv(turnover, "turnover.csv", row.names = FALSE)
cat("\nExported turnover.csv\n")

cat("\n=== 02_analysis.R complete ===\n")
cat("Objects ready: all_funds, turnover, turnover_summary\n")