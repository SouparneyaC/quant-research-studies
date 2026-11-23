"""The Citadel lagged-copy study: committed tables reproduce the original numbers, and the checks
that change the conclusion (same-date benchmark, factor alignment) hold."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

STUDY = Path(__file__).resolve().parents[1] / "studies" / "citadel-lag-backtest"
spec = importlib.util.spec_from_file_location("citadel_analysis", STUDY / "analysis.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


@pytest.fixture(scope="module")
def q():
    return analysis.load_quarterly()


def test_headline_numbers_as_originally_reported(q):
    h = analysis.headline_as_reported(q)
    assert h["full"] == pytest.approx(0.169, abs=0.0005)
    assert h["clone"] == pytest.approx(0.008, abs=0.0005)
    assert h["spy"] == pytest.approx(0.009, abs=0.0005)
    assert len(q) == 20


def test_benchmark_covers_fewer_days_than_the_full_alpha_leg(q):
    days = analysis.window_days(q)
    assert days["full"] == 1826
    assert days["post_filing"] == 926
    assert days["full"] == days["post_filing"] + days["to_filing"]


def test_no_leg_beats_spy_over_the_same_dates(q):
    like = analysis.like_for_like(q)
    full, clone = like.iloc[0], like.iloc[2]
    assert full["cum_strategy"] == pytest.approx(2.1826, abs=0.0005)
    assert full["cum_spy_same_dates"] == pytest.approx(2.3342, abs=0.0005)
    assert full["cum_strategy"] < full["cum_spy_same_dates"]
    assert clone["cum_strategy"] == pytest.approx(1.0404, abs=0.0005)
    assert clone["cum_spy_same_dates"] == pytest.approx(1.0457, abs=0.0005)
    assert (like["p_value"] > 0.5).all()


def test_market_model_on_matching_dates_finds_no_alpha(q):
    mm = analysis.market_model(q)
    assert (mm["alpha_p_value"] > 0.5).all()
    assert mm["beta"].between(0.95, 1.05).all()


def test_saved_factor_regressions_are_reproduced(q):
    saved = pd.read_csv(STUDY / "results" / "factor_regressions_saved.csv")
    mine = analysis.factor_regressions(q, aligned=False)
    name_map = {
        "Full Alpha (Theoretical)": "Full alpha (net of RF)",
        "Lagged Clone": "Lagged clone (net of RF)",
        "Alpha Gap (Full - Clone)": "Gap (full minus clone)",
    }
    n = 0
    for _, row in saved[saved["series"].isin(name_map)].iterrows():
        term = "alpha" if row["term"] == "(Intercept)" else row["term"]
        m = mine[(mine["series"] == name_map[row["series"]]) & (mine["term"] == term)]
        assert m["estimate"].iloc[0] == pytest.approx(row["estimate"], abs=1e-4)
        assert m["p_value"].iloc[0] == pytest.approx(row["p.value"], abs=1e-4)
        n += 1
    assert n == 15
    gap_alpha = mine[(mine["series"].str.startswith("Gap")) & (mine["term"] == "alpha")].iloc[0]
    assert gap_alpha["p_value"] == pytest.approx(0.0011, abs=0.0001)


def test_factor_rows_are_one_quarter_behind_the_returns(q):
    mkt, spy = q["Mkt_RF"].to_numpy(), q["spy_ret_full_quarter"].to_numpy()
    assert abs(np.corrcoef(mkt, spy)[0, 1]) < 0.1
    assert np.corrcoef(mkt[1:], spy[:-1])[0, 1] > 0.95


def test_aligned_factors_remove_the_apparent_alpha(q):
    reg = analysis.factor_regressions(q, aligned=True)

    def get(series, term, col):
        row = reg[(reg["series"].str.startswith(series)) & (reg["term"] == term)]
        return row[col].iloc[0]

    assert get("Full", "Mkt_RF", "estimate") == pytest.approx(0.957, abs=0.01)
    assert get("Full", "alpha", "p_value") > 0.3
    assert get("Gap", "alpha", "p_value") > 0.1
    assert (reg["n_quarters"] == 19).all()


def test_decay_curve_is_never_significant():
    dec = analysis.decay_tests()
    assert (dec["p_value"] > 0.05).all()
    assert set(dec["day"]) == {1, 2, 5, 10, 20, 30, 45, 60, 90}


def test_filing_lag_table_separates_amendments():
    lag = pd.read_csv(STUDY / "results" / "filing_lag_by_firm.csv").set_index("firm")
    assert lag.loc["citadel", "max_lag"] == 162
    assert lag.loc["citadel", "n_amendment_quarters"] == 2
    assert lag.loc["citadel", "orig_max_lag"] == 47
