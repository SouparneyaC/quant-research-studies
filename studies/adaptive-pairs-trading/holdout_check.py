"""Splits the pairs strategy's Sharpe ratio into the period the Random Forest was trained on and
the period it was not.

oil_copper_fitted_ML.py fits the classifier on the first 80% of the sample and then scores the
whole sample, so its headline Sharpe of 0.36 mixes in-sample and held-out days. This script
rebuilds the same signal (same data, filter, features, threshold and seed) and reports the
Sharpe ratio separately for each period, with and without the classifier.

Usage: python holdout_check.py   (downloads prices from Yahoo Finance)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from pykalman import KalmanFilter
from sklearn.ensemble import RandomForestClassifier

THRESHOLD = 2.0


def sharpe(x):
    x = x.dropna()
    return float(np.sqrt(252) * x.mean() / x.std()) if x.std() > 0 else 0.0


tickers = ["EWA", "EWC", "^VIX", "HG=F", "CL=F"]
prices = yf.download(tickers, start="2020-01-01", end="2025-12-31", progress=False)["Close"].dropna()
norm = (prices / prices.iloc[0]) * 100

obs = np.vstack([norm["EWC"], np.ones(len(norm))]).T[:, np.newaxis, :]
kf = KalmanFilter(
    n_dim_obs=1, n_dim_state=2, initial_state_mean=np.zeros(2),
    initial_state_covariance=np.ones((2, 2)), transition_matrices=np.eye(2),
    observation_matrices=obs, observation_covariance=1.0,
    transition_covariance=np.eye(2) * 1e-4,
)
state, _ = kf.filter(norm["EWA"].values)
norm["Smart_Spread"] = norm["EWA"] - (norm["EWC"] * state[:, 0] + state[:, 1])
norm["Oil_5D_Trend"] = prices["CL=F"].pct_change(5).shift(1)
norm["Copper_5D_Trend"] = prices["HG=F"].pct_change(5).shift(1)
norm["Spread_Vol"] = norm["Smart_Spread"].rolling(10).std()
norm["VIX_Level"] = norm["^VIX"]
norm["Target"] = (norm["Smart_Spread"].shift(-5).abs() < norm["Smart_Spread"].abs()).astype(int)

cols = ["Spread_Vol", "VIX_Level", "Oil_5D_Trend", "Copper_5D_Trend", "Smart_Spread"]
data = norm[cols + ["Target"]].dropna()
split = int(len(data) * 0.8)
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(data[cols][:split], data["Target"][:split])
train_end = data.index[split - 1]

wide = (norm["Smart_Spread"].abs() > norm["Spread_Vol"] * THRESHOLD).astype(int)
signal = pd.Series(np.where(wide == 1, model.predict(norm[cols].fillna(0)), 0), index=norm.index)
spread_change = norm["Smart_Spread"].diff()
norm["with_classifier"] = spread_change * signal.shift(1)
norm["threshold_only"] = spread_change * wide.shift(1)
norm["signal_days"] = signal

periods = {
    "full sample": norm.index == norm.index,
    f"training period (to {train_end.date()})": norm.index <= train_end,
    f"held-out period (after {train_end.date()})": norm.index > train_end,
}
print(f"{'period':40s} {'days':>5s} {'signal days':>11s} {'Sharpe, classifier':>19s} {'Sharpe, threshold only':>23s}")
for name, mask in periods.items():
    p = norm[mask]
    print(f"{name:40s} {len(p):5d} {int(p['signal_days'].sum()):11d} "
          f"{sharpe(p['with_classifier']):19.2f} {sharpe(p['threshold_only']):23.2f}")
