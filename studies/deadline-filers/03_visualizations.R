# 03_visualizations.R
# Strategic Opacity: 13F Filing Lag Analysis
# Generate all figures for the paper
# Please do install.packages(c("ggplot2", "dplyr", "scales", "ggrepel"))
# INPUT FILES (included in repo): turnover.csv and clean.csv
# Gives you all the plots for our findings as of yet.

library(ggplot2)
library(dplyr)
library(scales)

if (!requireNamespace("ggrepel", quietly = TRUE)) install.packages("ggrepel")
library(ggrepel)

# CONFIG
OUTPUT_FOLDER <- "strategic_opacity_plots"
dir.create(OUTPUT_FOLDER, showWarnings = FALSE)

save_fig <- function(filename, plot, width = 9, height = 6) {
  path <- file.path(OUTPUT_FOLDER, filename)
  ggsave(path, plot, width = width, height = height, dpi = 300, bg = "white")
  cat("Saved:", path, "\n")
}

# LOAD THE DATA
turnover <- read.csv("turnover.csv", stringsAsFactors = FALSE)
clean    <- read.csv("clean.csv",    stringsAsFactors = FALSE)

cat("Turnover rows:", nrow(turnover), "\n")
cat("Clean rows:",    nrow(clean),    "\n")

# SHARED THEME
qk_theme <- theme_minimal(base_size = 12) +
  theme(
    plot.title        = element_text(hjust = 0.5, size = 13, color = "#333333"),
    plot.subtitle     = element_text(hjust = 0.5, size = 10, color = "#888888"),
    plot.background   = element_rect(fill = "white", color = NA),
    panel.background  = element_rect(fill = "white", color = NA),
    panel.grid.major  = element_line(color = "#f0f0f0", linewidth = 0.5),
    panel.grid.minor  = element_blank(),
    axis.text         = element_text(color = "#888888", size = 9),
    axis.title        = element_text(color = "#888888", size = 10),
    legend.position   = "top",
    legend.background = element_rect(fill = "white", color = NA),
    legend.text       = element_text(color = "#666666", size = 9),
    legend.title      = element_blank(),
    plot.caption      = element_text(color = "#aaaaaa", size = 8, hjust = 1),
    plot.margin       = margin(20, 20, 10, 20),
    axis.ticks        = element_blank()
  )

TYPE_COLORS <- c(
  "deadline_hugger" = "#C17B7B",
  "early_filer"     = "#7B9EC1"
)

FUND_COLORS <- c(
  "SIG"       = "#C17B7B",
  "Parallax"  = "#7B9EC1",
  "Wolverine" = "#7BC17B"
)

# FIGURE 1: Position Turnover Boxplot
p1 <- ggplot(turnover,
             aes(x    = reorder(fund, turnover_pct),
                 y    = turnover_pct,
                 fill = type)) +
  geom_vline(xintercept = 2.5,
             linetype = "dashed", color = "#eeeeee", linewidth = 0.8) +
  geom_boxplot(alpha = 0.45, linewidth = 0.4,
               outlier.shape = NA, width = 0.45) +
  geom_jitter(aes(color = type), width = 0.12,
              alpha = 0.55, size = 2.2, show.legend = FALSE) +
  annotate("text", x = 3.8, y = 0.50,
           label = "4.6x higher\nturnover",
           color = "#C17B7B", size = 3.2, fontface = "italic",
           hjust = 0) +
  scale_fill_manual(
    values = TYPE_COLORS,
    labels = c("deadline_hugger" = "Deadline Hugger",
               "early_filer"     = "Early Filer")
  ) +
  scale_color_manual(values = TYPE_COLORS) +
  scale_y_continuous(labels = percent_format(accuracy = 1),
                     limits = c(0.02, 0.60)) +
  labs(
    title   = "Position Turnover vs Filing Behavior",
    x       = NULL,
    y       = "Quarterly Position Turnover",
    caption = "Source: QUANTkiosk 13F Data | 2023Q2-2025Q1"
  ) +
  qk_theme

# FIGURE 2: Filing Lag vs Turnover Scatter
p2 <- ggplot(turnover,
             aes(x = lag, y = turnover_pct, color = type)) +
  geom_hline(yintercept = mean(turnover$turnover_pct),
             linetype = "dashed", color = "#dddddd", linewidth = 0.7) +
  geom_point(size = 3.5, alpha = 0.75) +
  geom_text(aes(label = fund), vjust = -0.9, size = 2.8,
            show.legend = FALSE) +
  geom_smooth(method = "lm", se = FALSE,
              aes(group = type), linewidth = 0.9, alpha = 0.8) +
  scale_color_manual(
    values = TYPE_COLORS,
    labels = c("deadline_hugger" = "Deadline Hugger",
               "early_filer"     = "Early Filer")
  ) +
  scale_y_continuous(labels = percent_format(accuracy = 1)) +
  labs(
    title   = "Filing Lag Predicts Portfolio Turnover",
    x       = "Days from Quarter End to Filing",
    y       = "Position Turnover Rate",
    caption = "Source: QUANTkiosk 13F Data"
  ) +
  qk_theme

# FIGURE 3: Options Footprint Over Time
p3 <- turnover %>%
  filter(type == "deadline_hugger") %>%
  mutate(reportPeriod = as.factor(reportPeriod)) %>%
  ggplot(aes(x     = reportPeriod,
             y     = opt_pct,
             color = fund,
             group = fund)) +
  geom_hline(yintercept = 0.5,
             linetype = "dashed", color = "#dddddd", linewidth = 0.7) +
  geom_line(linewidth = 1.2, alpha = 0.9) +
  geom_point(size = 3, alpha = 0.9) +
  scale_color_manual(values = FUND_COLORS) +
  scale_y_continuous(labels = percent_format(accuracy = 1),
                     limits = c(0.30, 0.85)) +
  labs(
    title   = "Options Footprint of Deadline Huggers",
    x       = NULL,
    y       = "Options as % of Positions",
    caption = "Source: QUANTkiosk 13F Data"
  ) +
  qk_theme +
  theme(axis.text.x = element_text(angle = 45, hjust = 1, size = 8))

# FIGURE 4: Annual Trend 2013-2025
clean$year     <- as.numeric(substr(as.character(clean$period), 1, 4))
clean$lag_true <- as.numeric(clean$lag_true)
clean$optpct   <- as.numeric(clean$optpct)

annual <- clean %>%
  group_by(year) %>%
  summarise(
    pct_deadline = mean(lag_true >= 43, na.rm = TRUE),
    avg_optpct   = mean(optpct,         na.rm = TRUE),
    .groups = "drop"
  )

scale_factor <- max(annual$pct_deadline) / max(annual$avg_optpct)

p4 <- ggplot(annual, aes(x = year)) +
  geom_line(aes(y = pct_deadline,
                color = "% Filing Day 43-45"),
            linewidth = 1.3) +
  geom_point(aes(y = pct_deadline,
                 color = "% Filing Day 43-45"),
             size = 3) +
  geom_line(aes(y = avg_optpct * scale_factor,
                color = "Avg Options %"),
            linewidth = 1.3, linetype = "dashed") +
  geom_point(aes(y = avg_optpct * scale_factor,
                 color = "Avg Options %"),
             size = 3) +
  scale_y_continuous(
    labels   = percent_format(accuracy = 1),
    sec.axis = sec_axis(~ . / scale_factor,
                        name   = "Average Options %",
                        labels = percent_format(accuracy = 0.1))
  ) +
  scale_color_manual(values = c(
    "% Filing Day 43-45" = "#C17B7B",
    "Avg Options %"      = "#7B9EC1"
  )) +
  scale_x_continuous(breaks = seq(2013, 2025, 2)) +
  labs(
    title   = "Deadline-Hugging and Derivatives Exposure: 2013-2025",
    x       = NULL,
    y       = "% Filing on Day 43-45",
    caption = "Source: QUANTkiosk 13F Data | 11,870 institutions"
  ) +
  qk_theme

# PRINT AND SAVE
print(p1)
print(p2)
print(p3)
print(p4)

save_fig("fig1_turnover_boxplot.png",  p1, width = 9,  height = 6)
save_fig("fig2_lag_scatter.png",       p2, width = 9,  height = 6)
save_fig("fig3_options_footprint.png", p3, width = 9,  height = 5)
save_fig("fig4_annual_trend.png",      p4, width = 11, height = 6)

cat("\nAll figures saved to:", normalizePath(OUTPUT_FOLDER), "\n")
cat("=== 03_visualizations.R complete ===\n")