"""The committed result tables agree with the numbers the study README reports."""

from math import erf, sqrt
from pathlib import Path

import pandas as pd
import pytest

RESULTS = Path(__file__).resolve().parents[1] / "studies" / "amendment-disclosure" / "results"


def read(name):
    return pd.read_csv(RESULTS / name)


def test_sample_sizes():
    comp = read("sample_composition.csv").set_index("metric")["value"]
    assert int(comp["N treated funds"]) == 4254
    assert int(comp["N control funds"]) == 3522
    assert int(comp["N fund-quarter obs (total)"]) == 81121
    assert int(comp["N fund-quarter obs (treated)"]) + int(comp["N fund-quarter obs (control)"]) == 81121


def test_amendment_quarter_effect():
    main = read("coefs_main.csv").set_index("event_time")
    k0 = main.loc[0]
    assert k0["coef"] == pytest.approx(0.0172, abs=0.0001)
    t = k0["coef"] / k0["se"]
    p = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))
    assert p == pytest.approx(0.027, abs=0.002)
    assert main.loc[-1, "coef"] == 0.0          # reference period
    assert k0["ci_lo"] > 0                      # the interval excludes zero


def test_effect_survives_fund_trends():
    trends = read("coefs_with_trends.csv").set_index("event_time")
    assert trends.loc[0, "coef"] == pytest.approx(0.0168, abs=0.0001)


def test_pre_trends_and_placebo():
    pre = read("pretrend_test.csv").iloc[0]
    assert pre["F_stat"] == pytest.approx(1.35, abs=0.01)
    assert pre["p_value"] == pytest.approx(0.23, abs=0.01)
    placebo = read("coefs_placebo.csv").set_index("event_time").loc[0]
    assert placebo["coef"] == pytest.approx(-0.0121, abs=0.0001)
    assert abs(placebo["coef"]) < 1.96 * placebo["se"]


def test_average_post_effect_is_zero():
    did = read("did_simple.csv").iloc[0]
    assert did["coef"] == pytest.approx(-0.0013, abs=0.0001)
    assert did["pvalue"] == pytest.approx(0.68, abs=0.01)


def test_bacon_weights():
    s = read("bacon_decomp_summary.csv").set_index("type")
    assert s["total_weight"].sum() == pytest.approx(1.0, abs=1e-6)
    assert s.loc["Later vs. Earlier treated (biased)", "total_weight"] == pytest.approx(0.291, abs=0.001)
    assert int(s["n_pairs"].sum()) == 2282
