# 01_load_and_build.R

library(qkiosk)
library(dplyr)

# 1. API KEY
qk_set_apikey(Sys.getenv("QK_API_KEY"))

data <- qk_download()

cat("Loaded", nrow(data), "rows\n")
cat("Time range:", range(data$period), "\n")
cat("Unique institutions:", length(unique(data$cik)), "\n")
cat("Missing filed dates:", sum(is.na(data$filed)), "\n")

data$lag_true <- as.numeric(
  as.Date(as.character(data$filed),  "%Y%m%d") -
    as.Date(as.character(data$period), "%Y%m%d")
)

cat("\n--- Filing Lag Summary (days from quarter end) ---\n")
print(summary(data$lag_true))


# 4. SIZE BUCKETS (Quartile-based AUM classification)
data$size_bucket <- cut(
  data$valueTotal,
  breaks = quantile(data$valueTotal, c(0, 0.25, 0.5, 0.75, 1), na.rm = TRUE),
  labels = c("small", "mid", "large", "mega")
)

cat("\n--- Lag by Size Bucket ---\n")
print(tapply(data$lag_true, data$size_bucket, summary))

cat("\n--- Options % by Size Bucket ---\n")
print(round(tapply(data$optpct, data$size_bucket, mean, na.rm = TRUE), 4))

# 5. FILTER TO CLEAN FILINGS
# Removes foreign administrative backfill (4000+ day outliers)
# Removes impossible values (negative lag)
# Legal window = 0-45 days; using 0-50 to allow minor SEC extensions
clean <- data[data$lag_true >= 0 & data$lag_true <= 50, ]

cat("\nClean filings:", nrow(clean), "of", nrow(data),
    paste0("(", round(nrow(clean)/nrow(data)*100, 1), "%)\n"))

# 6. CLASSIFING FILING BEHAVIOR
# deadline_hugger = filing on day 43-45 (within 2 days of deadline)
# early           = filing before day 43
clean$filing_behavior <- ifelse(
  clean$lag_true >= 43, "deadline_hugger", "early"
)

cat("\n--- Core Correlation: Filing Lag vs Options % ---\n")
cat("Pearson r:", round(cor(clean$lag_true, clean$optpct,
                            use = "complete.obs"), 4), "\n")

cat("\n--- Mean optpct by Filing Behavior ---\n")
print(round(tapply(clean$optpct, clean$filing_behavior, mean, na.rm=TRUE), 4))

cat("\n--- Median AUM by Filing Behavior ---\n")
print(tapply(clean$valueTotal, clean$filing_behavior, median, na.rm=TRUE))

# 7. BUILDING CONSISTENCY DATAFRAME
# Aggregate filing behavior per institution across all available quarters with minimum 8 filings (at least 2 full years of data)
consistency <- clean %>%
  group_by(cik, name) %>%
  summarise(
    avg_lag      = mean(lag_true,     na.rm = TRUE),
    avg_optpct   = mean(optpct,       na.rm = TRUE),
    median_value = median(valueTotal, na.rm = TRUE),
    n_filings    = n(),
    pct_deadline = mean(lag_true >= 43, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  filter(n_filings >= 8) %>%
  arrange(desc(pct_deadline))

cat("\nInstitutions in consistency df:", nrow(consistency), "\n")

# IDENTIFY TARGET INSTITUTIONS FOR STAGE 2
# Huggers:  >= 75% of filings at deadline AND >= 8 filings
# Early:    <= 25% of filings at deadline AND largest AUM (control group)
target_huggers <- consistency %>%
  filter(pct_deadline >= 0.75, n_filings >= 8) %>%
  arrange(desc(avg_optpct)) %>%
  head(20)

target_early <- consistency %>%
  filter(pct_deadline <= 0.25, n_filings >= 8) %>%
  arrange(desc(median_value)) %>%
  head(20)

cat("\n--- Top 20 Chronic Deadline Huggers ---\n")
print(target_huggers[, c("name", "avg_lag", "avg_optpct",
                         "pct_deadline", "median_value", "n_filings")])

cat("\n--- Top 20 Chronic Early Filers (size-matched control) ---\n")
print(target_early[, c("name", "avg_lag", "avg_optpct",
                       "pct_deadline", "median_value", "n_filings")])

# Optional Python visualization because R plotting sucks.
# PYTHON VISUALIZATION
write.csv(clean, "clean.csv", row.names = FALSE)
cat("\nExported clean.csv\n")

cat("\n=== 01_load_and_build.R complete ===\n")
cat("Objects ready: data, clean, consistency, target_huggers, target_early\n")