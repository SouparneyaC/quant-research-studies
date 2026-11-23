# ─────────────────────────────────────────────────────────────────────────────
# 01_fetch_holdings.R
# Purpose: Fetch 21 quarters of Citadel Advisors 13-F institutional holdings
#          from the QUANTkiosk API and save locally as an RDS cache.
#
# Output:  data/holdings_raw.rds
#          data/citadel_qkid.rds
#
# IMPORTANT: Run interactively the first time so qk_search_mgr() can prompt
#            for selection. After that the QKID is cached and Rscript works.
# ─────────────────────────────────────────────────────────────────────────────

library(qkiosk)
library(dplyr)

qk_set_apikey(Sys.getenv("QK_API_KEY"))

# ── Config ────────────────────────────────────────────────────────────────────
QKID_PATH   <- "data/citadel_qkid.rds"
OUTPUT_PATH <- "data/holdings_raw.rds"

# All 21 quarters: 2020 Q1 through 2025 Q1
# Confirmed available in availability check
QUARTERS <- c(
  202001, 202002, 202003, 202004,
  202101, 202102, 202103, 202104,
  202201, 202202, 202203, 202204,
  202301, 202302, 202303, 202304,
  202401, 202402, 202403, 202404,
  202501
)

dir.create("data", showWarnings = FALSE)

# ── Resolve Citadel QKID ──────────────────────────────────────────────────────
if (file.exists(QKID_PATH)) {
  citadel_qkid <- readRDS(QKID_PATH)
  cat("Loaded cached QKID\n")
} else {
  cat("Searching for Citadel: select CITADEL ADVISORS LLC from the list.\n")
  citadel_qkid <- qk_search_mgr("citadel")
  saveRDS(citadel_qkid, QKID_PATH)
  cat("QKID cached to", QKID_PATH, "\n")
}

cat("Fund:", to_name(citadel_qkid), "\n\n")

# ── Fetch Quarter by Quarter ──────────────────────────────────────────────────
# Fetching individually because the YYYY00 full-year syntax returns unavailable
# for this filer. Each quarter is fetched, converted to plain data.frame, and
# appended to the list.

holdings_list <- lapply(QUARTERS, function(q) {
  result <- tryCatch({
    data <- qk_institutional(citadel_qkid, yyyyqq = q, qtrs = 1, agg = TRUE)
    as.data.frame(data)
  }, error = function(e) {
    cat("  ERROR on quarter", q, ":", e$message, "\n")
    NULL
  })
  Sys.sleep(0.5)   # polite pause between calls
  result
})

# ── Combine ───────────────────────────────────────────────────────────────────
holdings_raw <- bind_rows(holdings_list)
cat("\nTotal rows fetched:", nrow(holdings_raw), "\n")

# ── Enrich ────────────────────────────────────────────────────────────────────
holdings_raw <- holdings_raw |>
  mutate(
    ticker           = issuerTicker,
    name             = issuer,
    quarter_end_date = as.Date(as.character(reportPeriod), format = "%Y%m%d"),
    filing_date      = quarter_end_date + 45
  )

# ── Inspect ────────────────────────────────────────────