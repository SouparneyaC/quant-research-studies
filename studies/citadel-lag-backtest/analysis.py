"""Recomputes the Citadel lagged-copy backtest results from the committed quarter-level tables.

The code that built the original backtest was not saved, so this starts from the
quarter-level returns it left behind (results/quarterly_returns.csv) and redoes the
three steps that decide the conclusion:

  1. Compare each strategy with SPY over the SAME dates.
  2. Rerun the factor regressions, as saved and with the factors lined up to the returns.
  3. Test the decay curve with standard errors across quarters.

Usage:
    python analysis.py            # writes tables (and figures, if matplotlib is installed) to results/
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
FACTORS = ["Mkt_RF", "SMB", "HML", "UMD"]

# Each strategy leg, the SPY column over the same dates, and the dates it is invested.
LEGS = {
    "Full alpha (quarter-end to next quarter-end)": ("port_ret_full_alpha", "spy_ret_full_quarter"),
    "Leakage (quarter-end to filing day)": ("port_ret_leakage", "spy_ret_to_filing"),
    "Lagged clone (filing day to next quarter-end)": ("port_ret_clone", "spy_ret_post_filing"),
}


def load_quarterly(path=None):
    cols = ["quarter_end_date", "filing_date", "next_quarter_end"]
    return pd.read_csv(path or RESULTS / "quarterly_returns.csv", parse_dates=cols)


def cumulative(r):
    return float(np.prod(1.0 + np.asarray(r, dtype=float)))


def ols(y, X):
    """OLS with an intercept. Returns coefficients, standard errors, p-values and R-squared."""
    y = np.asarray(y, dtype=float)
    X = np.column_stack([np.ones(len(y)), np.asarray(X, dtype=float).reshape(len(y), -1)])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    n, k = X.shape
    cov = resid @ resid / (n - k) * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    p = 2 * stats.t.sf(np.abs(beta / se), n - k)
    r2 = 1 - resid @ resid / ((y - y.mean()) @ (y - y.mean()))
    return {"coef": beta, "se": se, "p": p, "r2": float(r2), "n": n}


def headline_as_reported(q, years=5):
    """The report's table: cumulative growth annualised over 5 years, SPY on the post-filing dates."""
    out = {}
    for key, col in [("full", "port_ret_full_alpha"), ("clone", "port_ret_clone"), ("spy", "spy_ret_post_filing")]:
        out[key] = cumulative(q[col]) ** (1 / years) - 1
    return out


def like_for_like(q):
    """Each leg against SPY over the same dates: cumulative growth, mean quarterly gap, t-test."""
    rows = []
    for name, (leg, spy) in LEGS.items():
        gap = q[leg] - q[spy]
        t = stats.ttest_1samp(gap, 0.0)
        rows.append(
            {
                "leg": name,
                "cum_strategy": cumulative(q[leg]),
                "cum_spy_same_dates": cumulative(q[spy]),
                "mean_quarterly_gap": float(gap.mean()),
                "t_stat": float(t.statistic),
                "p_value": float(t.pvalue),
                "n_quarters": len(gap),
            }
        )
    return pd.DataFrame(rows)


def window_days(q):
    return {
        "full": int((q["next_quarter_end"] - q["quarter_end_date"]).dt.days.sum()),
        "post_filing": int((q["next_quarter_end"] - q["filing_date"]).dt.days.sum()),
        "to_filing": int((q["filing_date"] - q["quarter_end_date"]).dt.days.sum()),
    }


def _dependent_series(q, aligned):
    """Series to regress. Aligned drops the last quarter and uses the next row's risk-free rate."""
    full, clone, rf = q["port_ret_full_alpha"], q["port_ret_clone"], q["RF"]
    if aligned:
        return {
            "Full alpha (net of RF)": (full.iloc[:-1] - rf.iloc[1:].to_numpy()).to_numpy(),
            "Lagged clone (net of RF)": (clone.iloc[:-1] - rf.iloc[1:].to_numpy()).to_numpy(),
            "Gap (full minus clone)": (full - clone).iloc[:-1].to_numpy(),
        }
    return {
        "Full alpha (net of RF)": (full - rf).to_numpy(),
        "Lagged clone (net of RF)": (clone - rf).to_numpy(),
        "Gap (full minus clone)": (full - clone).to_numpy(),
    }


def factor_regressions(q, aligned):
    """Four-factor regressions of each series on the factor columns.

    aligned=False reproduces the saved results: factor row i is the quarter that ENDS on
    quarter_end_date, while return row i is the quarter that STARTS there. aligned=True pairs each
    return with the factors of the quarter it actually covers (the next row), which drops the last
    quarter because its factors are not in the table.
    """
    F = q[FACTORS].to_numpy()
    X = F[1:] if aligned else F
    rows = []
    for name, y in _dependent_series(q, aligned).items():
        res = ols(y, X)
        for i, term in enumerate(["alpha"] + FACTORS):
            rows.append(
                {
                    "series": name,
                    "alignment": "factors aligned to the return quarter" if aligned else "as saved",
                    "term": term,
                    "estimate": res["coef"][i],
                    "std_error": res["se"][i],
                    "p_value": res["p"][i],
                    "r_squared": res["r2"],
                    "n_quarters": res["n"],
                }
            )
    return pd.DataFrame(rows)


def market_model(q):
    """Each leg on SPY over its own dates: alpha, beta, R-squared. No factor timing involved."""
    rows = []
    for name, (leg, spy) in LEGS.items():
        res = ols(q[leg], q[spy])
        rows.append(
            {
                "leg": name,
                "alpha_per_quarter": res["coef"][0],
                "alpha_p_value": res["p"][0],
                "beta": res["coef"][1],
                "r_squared": res["r2"],
                "n_quarters": res["n"],
            }
        )
    return pd.DataFrame(rows)


def decay_tests(path=None):
    """Average excess return over SPY by day after quarter-end, tested across quarters."""
    d = pd.read_csv(path or RESULTS / "decay_by_quarter.csv")
    d["excess"] = d["mean_raw_return"] - d["spy_return"]
    g = d.groupby("day")["excess"].agg(["mean", "std", "count"]).reset_index()
    g["std_error"] = g["std"] / np.sqrt(g["count"])
    g["t_stat"] = g["mean"] / g["std_error"]
    g["p_value"] = 2 * stats.t.sf(np.abs(g["t_stat"]), g["count"] - 1)
    return g.rename(columns={"mean": "mean_excess", "count": "n_quarters"}).drop(columns="std")


def main():
    q = load_quarterly()
    like = like_for_like(q)
    regs = pd.concat([factor_regressions(q, False), factor_regressions(q, True)], ignore_index=True)
    mm = market_model(q)
    dec = decay_tests()
    like.round(5).to_csv(RESULTS / "like_for_like.csv", index=False)
    regs.round(5).to_csv(RESULTS / "regressions_recomputed.csv", index=False)
    mm.round(5).to_csv(RESULTS / "market_model.csv", index=False)
    dec.round(5).to_csv(RESULTS / "decay_tests.csv", index=False)

    print("As reported (annualised over 5 years):", {k: round(v, 4) for k, v in headline_as_reported(q).items()})
    print("Days invested per window:", window_days(q))
    print(like.round(4).to_string(index=False))
    print(mm.round(4).to_string(index=False))
    print(dec.round(4).to_string(index=False))
    make_figures(q, dec)


def make_figures(q, dec):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed: skipping figures")
        return
    fig_dir = HERE / "figures"
    fig_dir.mkdir(exist_ok=True)

    fig, ax = plt.subplots(figsize=(9, 5))
    for name, (leg, spy) in LEGS.items():
        short = name.split(" (")[0]
        ax.plot(q["next_quarter_end"], 100 * (np.cumprod(1 + q[leg]) / np.cumprod(1 + q[spy]) - 1),
                marker="o", ms=3, label=short)
    ax.axhline(0, color="grey", lw=0.8, ls=":")
    ax.set_ylabel("Strategy growth relative to SPY, same dates (%)")
    ax.set_title("Citadel 13F copy: each leg against SPY over the same dates")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(fig_dir / "like_for_like.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.errorbar(dec["day"], 100 * dec["mean_excess"], yerr=200 * dec["std_error"], fmt="o-", capsize=3)
    ax.axhline(0, color="grey", lw=0.8)
    ax.axvline(45, color="#c0392b", lw=1, ls="--")
    ax.text(46, ax.get_ylim()[1] * 0.9, "day 45: filing", color="#c0392b", fontsize=9)
    ax.set_xlabel("Days after quarter-end")
    ax.set_ylabel("Mean excess return over SPY (%), bars = 2 SE")
    ax.set_title("Holdings versus SPY after quarter-end: no measurable gap at any horizon")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(fig_dir / "decay_with_error_bars.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
