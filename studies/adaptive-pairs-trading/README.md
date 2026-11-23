# Adaptive Pairs Trading

Code for "Adaptive Pairs Trading: Integrating State-Space Models and Non-Linear Classifiers in
Commodity-Linked Equities" (`paper.pdf`, source `paper.docx`).

Data: Yahoo Finance prices through `yfinance`. No API key, and no QuantKiosk or other vendor data.

A pairs trade between the MSCI Australia (EWA) and MSCI Canada (EWC) ETFs, 2020-2025, using a
Kalman filter to estimate a time-varying hedge ratio instead of a fixed one, and a Random Forest
classifier to gate trade entries on macro conditions (VIX level, oil and copper trend). Result:
Sharpe 0.36 on 72 active trading days, most of the return earned by staying out of the market
during a 2024 structural divergence between the two ETFs.

## Requirements

```
pip install yfinance pandas numpy matplotlib pykalman scikit-learn
```

## Running the scripts

Each script downloads its own data via `yfinance` on run; there is no separate data-download
step. Run them in this order to reproduce the paper's own figures and headline result:

```
python3 importing_data.py       # Figure 1: price/spread divergence
python3 kalman_filter.py        # Figure 2: naive vs. Kalman-filtered spread
python3 oil_copper_fitted_ML.py # Figure 3 and the paper's reported Sharpe of 0.36
```

`ML_Model.py` and `sharpe_ratio.py` are earlier versions of the classifier, kept as-is: both fit
the Random Forest on spread volatility, VIX, and the Kalman spread alone, without the oil and
copper trend features. `oil_copper_fitted_ML.py` is the version whose output matches the paper's
own reported numbers; its terminal Sharpe ratio is printed directly in its plot title.

## File of origin

| Figure / result | Generating file |
|---|---|
| Figure 1 (price and spread divergence) | `importing_data.py` |
| Figure 2 (naive vs. Kalman spread) | `kalman_filter.py` |
| Figure 3 (final equity curve, Sharpe 0.36) | `oil_copper_fitted_ML.py` |
| Table 2, baseline row | `oil_copper_fitted_ML.py`, threshold 2.0, 5-day oil/copper trend |
| Table 2, alternative row | `oil_copper_fitted_ML.py`, threshold changed to 1.25, trend window changed to 1 day (not saved as a separate file) |

## Data

All price data (EWA, EWC, VIX, and the CL=F/HG=F futures used as macro features) is pulled
directly from Yahoo Finance via `yfinance` at runtime. No data files are stored in this
repository; running any script reproduces the same date range (2020-01-01 through 2025-12-31)
from the live source.

## Note on the two development-stage scripts

`ML_Model.py` and `sharpe_ratio.py` reflect an earlier stage of the project, before the oil and
copper trend features described in the paper's own methodology were added. They are kept in the
repository as-is rather than deleted, since they're real steps in how the final model was
reached, not dead code.
