# Adaptive Pairs Trading

A pairs trade between two country ETFs, using a Kalman filter for a changing hedge ratio and a Random Forest to decide when to enter. Code for "Adaptive Pairs Trading: Integrating State-Space Models and Non-Linear Classifiers in Commodity-Linked Equities" (`paper.pdf`, source `paper.docx`).

Data: Yahoo Finance prices through `yfinance`. No API key, and no QuantKiosk or other vendor data.

## Overview

The pair is the MSCI Australia (EWA) and MSCI Canada (EWC) ETFs, 2020 to 2025, which move together until a structural break in 2024.

- A Kalman filter estimates a time-varying hedge ratio between the two, in place of a fixed one
- A Random Forest classifier gates trade entries on macro conditions: the VIX level, and the oil and copper trend
- A trade is entered when the spread is wider than 2.0 times its 10-day volatility and the classifier says the spread will narrow within five days

## Results

Sharpe ratio 0.36 on 72 active trading days, most of the return earned by staying out of the market during the 2024 divergence between the two ETFs.

| Figure / result | Generating file |
|---|---|
| Figure 1 (price and spread divergence) | `importing_data.py` |
| Figure 2 (naive vs. Kalman spread) | `kalman_filter.py` |
| Figure 3 (final equity curve, Sharpe 0.36) | `oil_copper_fitted_ML.py` |
| Table 2, baseline row | `oil_copper_fitted_ML.py`, threshold 2.0, 5-day oil/copper trend |
| Table 2, alternative row | `oil_copper_fitted_ML.py`, threshold changed to 1.25, trend window changed to 1 day (not saved as a separate file) |

## Limits

The 0.36 is not an out-of-sample result. `oil_copper_fitted_ML.py` fits the classifier on the first 80% of the days and then scores the whole sample. `holdout_check.py` splits the same signal by period:

| Period | Days | Signal days | Sharpe with classifier | Sharpe, threshold rule only |
|---|---|---|---|---|
| Full sample | 1,507 | 72 | 0.36 | 0.06 |
| Training period (to 2024-10-17) | 1,207 | 52 | 0.03 | -0.28 |
| Held-out period | 300 | 20 | 1.36 | 1.36 |

- The classifier lifts the training-period Sharpe from -0.28 to 0.03, the part it was fitted on. On the 300 held-out days the strategy has the same Sharpe with or without it, so the data do not show the classifier adding anything out of sample.
- The held-out Sharpe of 1.36 rests on 20 signal days during the 2024 divergence. It is not a stable estimate.
- Profit is measured in units of the normalised spread, with no transaction costs, and the position is always long the spread on a signal day, whatever the sign of the spread.
- Prices are downloaded live. Yahoo can revise adjusted prices, so a rerun can differ slightly from the figures above, which were obtained in 2026.

## Usage

Python 3.12. Each script downloads its own data on run; there is no separate data step.

```bash
pip install -r requirements.txt
python3 importing_data.py        # Figure 1: price/spread divergence
python3 kalman_filter.py         # Figure 2: naive vs. Kalman-filtered spread
python3 oil_copper_fitted_ML.py  # Figure 3 and the paper's reported Sharpe of 0.36
python3 holdout_check.py         # Sharpe by training and held-out period
```

`oil_copper_fitted_ML.py` prints its terminal Sharpe ratio in the plot title.

## Project Structure

```
├── importing_data.py          # Figure 1
├── kalman_filter.py           # Figure 2
├── oil_copper_fitted_ML.py    # final strategy, Figure 3, headline Sharpe
├── holdout_check.py           # Sharpe split into training and held-out periods
├── ML_Model.py                # earlier classifier, without oil and copper features
├── sharpe_ratio.py            # earlier classifier, without oil and copper features
├── requirements.txt
├── figures/
├── paper.pdf
└── paper.docx
```

## Notes

- All price data (EWA, EWC, VIX, and the CL=F and HG=F futures used as macro features) is pulled from Yahoo Finance at run time, 2020-01-01 to 2025-12-31. No data files are stored here.
- `ML_Model.py` and `sharpe_ratio.py` are earlier stages, before the oil and copper features in the paper's methodology were added. They fit the Random Forest on spread volatility, VIX and the Kalman spread alone. They are kept as the record of how the final model was reached.
- This is a research exercise, not a trading recommendation.
