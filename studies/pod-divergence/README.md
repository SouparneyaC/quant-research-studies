# Intra-Firm Divergence as a Volatility Predictor

Finds stocks where the independent pods inside a multi-strategy hedge fund trade opposite sides of the same position. Case study: D.E. Shaw & Co., first quarter of 2024.

Data: QuantKiosk 13F submanager-level holdings. A D.E. Shaw sample (`deshaw`, 6,482 position rows) ships with the [`qkiosk`](https://github.com/quantkiosk/qkiosk-r) R package, so the scanner runs without an API key.

## Overview

A multi-strategy fund files one 13F for the whole firm, but trades through semi-autonomous pods with separate profit and loss. Two pods can be on opposite sides of a stock in the same quarter, and the firm-level filing shows only the net.

- Submanager-level positions instead of the firm total
- A spread score between the most-buying and most-selling pod
- Three named signal types
- Butterfly charts of each pod's change in one stock

## The Friction Index

For a stock held by pods `i = 1..n`, each with a quarter-over-quarter share change `pct_i`:

    friction = max(pct_i) - min(pct_i)

A position counts as internally hedged only when at least one pod is buying and at least one is selling. Pods that all buy, in different amounts, do not count. The scanner keeps positions of at least $1M and at least two pods, and scores the spread:

| Spread | Score |
|---|---|
| 100% or more | 100 |
| 50% to 100% | 75 |
| 20% (the default threshold) to 50% | 50 |

The three signal types compare the fund's net change with the most extreme pod:
- Internal disagreement: net change under 10% in size, spread above 50%
- Hidden accumulation: net buying, with one pod down more than 15%
- Contrarian opportunity: net selling, with one pod up more than 15%

## Results

The paper (`Intra-Firm-Divergence-as-a-Volatility-Predictor.pdf`, dated 2026-01-05) reports three case studies from the Q1 2024 filings:

| Ticker | Spread | Net change | Pods (buying / selling) | Total value |
|---|---|---|---|---|
| CELH | 20,674.8% | +1,363.3% | 1 / 1 | $132.1M |
| MCHP | 2,168.3% | +283.9% | 1 / 1 | $79.9M |
| NVDA | 56.7% | -37.9% | 1 / 2 | $2,110.1M |

The tables are in `results/` and the charts in `figures/`. NVDA reads as coordinated profit-taking: two pods cut by 56.5% and 21.2%, and the paper reports a 0.30% change in realized volatility after the filing.

## Usage

```r
install.packages("remotes")
remotes::install_github("quantkiosk/qkiosk-r")
library(qkiosk); library(dplyr); library(tidyr)
data(deshaw)

source("hedging_scanner.R")
source("hedging_visualizer.R")
scan_hedging_opportunities(deshaw, top_n = 20, export_csv = FALSE)
```

`scan_hedging_opportunities()` is the entry point and `calculate_hedging()` returns the scored table. `create_butterfly_chart(deshaw, "<ticker>")` draws one stock.

## Limits

- The case-study figures come from the pull used for the paper. The `deshaw` sample in the current `qkiosk` release (0.2.24) has the same 6,482 rows but different quarter-over-quarter values. On it the scanner flags AYI and GOLF and does not reproduce CELH, MCHP or NVDA. The committed tables and charts are the record of the paper's numbers.
- The volatility link is a hypothesis. The paper reports one post-filing volatility check (NVDA). It does not test whether friction predicts volatility across stocks, and no script for that test is included.
- This is a research signal. It is not a trading strategy and has no backtested profit and loss.
- The 13F is filed up to 45 days after quarter end, so every signal describes a position that is already history.

## Project Structure

| File | What it does |
|---|---|
| `hedging_scanner.R` | Scores every position and classifies the signals |
| `hedging_visualizer.R` | Butterfly chart of each pod's position change for one ticker |
| `results/` | Case-study tables for CELH, MCHP and NVDA |
| `figures/` | The three butterfly charts |

## Notes

- This is not affiliated with QuantKiosk or D.E. Shaw.
