import numpy as np
import pandas as pd
import pytest

from qk13f.kappa import build_beta, calc_kappa, ihhi, kappa_contributions


def stakes(**kw):
    return pd.Series(kw, dtype=float)


def test_kappa_is_one_for_identical_owners():
    b = stakes(a=0.10, b=0.05, c=0.02)
    assert calc_kappa(b, b) == pytest.approx(1.0)


def test_kappa_is_zero_for_disjoint_owners():
    assert calc_kappa(stakes(a=0.1, b=0.2), stakes(c=0.3, d=0.1)) == pytest.approx(0.0)


def test_kappa_matches_a_hand_calculation_and_is_asymmetric():
    f, g = stakes(a=0.1, b=0.2), stakes(a=0.2, b=0.1)
    assert calc_kappa(f, g) == pytest.approx((0.1 * 0.2 + 0.2 * 0.1) / (0.1**2 + 0.2**2))
    assert calc_kappa(f, g) == pytest.approx(0.8)
    h = stakes(a=0.4, b=0.0)
    assert calc_kappa(f, h) != pytest.approx(calc_kappa(h, f))


def test_kappa_is_undefined_without_owners():
    assert np.isnan(calc_kappa(pd.Series(dtype=float), stakes(a=0.1)))


def test_ihhi():
    assert ihhi(stakes(a=0.3, b=0.4)) == pytest.approx(0.25)


def test_group_contributions_sum_exactly_to_kappa():
    rng = np.random.default_rng(1)
    investors = [f"inv{i}" for i in range(40)]
    f = pd.Series(rng.uniform(0, 0.05, 40), index=investors)
    g = pd.Series(rng.uniform(0, 0.05, 40), index=investors)
    groups = {inv: ("big" if i < 3 else "mid" if i < 15 else "small")
              for i, inv in enumerate(investors)}
    parts = kappa_contributions(f, g, groups)
    assert set(parts) == {"big", "mid", "small"}
    assert sum(parts.values()) == pytest.approx(calc_kappa(f, g), rel=1e-12)


def test_unmapped_investors_fall_into_other_and_still_sum():
    f, g = stakes(a=0.1, b=0.2, c=0.05), stakes(a=0.2, b=0.1, d=0.3)
    parts = kappa_contributions(f, g, {"a": "named"})
    assert "other" in parts
    assert sum(parts.values()) == pytest.approx(calc_kappa(f, g))


def _holdings():
    return pd.DataFrame({
        "ticker": ["AAA", "AAA", "AAA", "BBB"],
        "filer_cik": ["1", "2", "3", "1"],
        "shares_held": [100, 50, 10, 40],
    })


def test_build_beta_consolidates_filers_under_one_parent():
    shares = pd.DataFrame({"ticker": ["AAA", "BBB"], "shares": [1000, 400]})
    beta = build_beta(_holdings(), shares, {"1": "P", "2": "P"}, {}, 2020, 1, ["AAA", "BBB"])
    assert beta["AAA"]["P"] == pytest.approx(0.15)
    assert beta["AAA"]["3"] == pytest.approx(0.01)
    assert beta["BBB"]["P"] == pytest.approx(0.10)


def test_build_beta_applies_scale_factor_and_caps_at_one():
    shares = pd.DataFrame({"ticker": ["AAA", "BBB"], "shares": [1000, 400]})
    scaled = build_beta(_holdings(), shares, {}, {("AAA", 2020, 1): 0.5}, 2020, 1, ["AAA"])
    assert scaled["AAA"]["1"] == pytest.approx(0.05)
    capped = build_beta(_holdings(), pd.DataFrame({"ticker": ["AAA"], "shares": [10]}),
                        {}, {}, 2020, 1, ["AAA"])
    assert capped["AAA"].max() == 1.0


def test_build_beta_returns_empty_without_a_share_count():
    beta = build_beta(_holdings(), pd.DataFrame({"ticker": [], "shares": []}),
                      {}, {}, 2020, 1, ["AAA"])
    assert beta["AAA"].empty
