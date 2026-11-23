import pytest

from qk13f.quality import (
    coverage_ratio,
    exceeds_full_ownership,
    is_doubled,
    is_partial_gap,
    matches_split_ratio,
    scale_error_factor,
)


@pytest.mark.parametrize("prev, cur, expected", [
    (100, 1000, 10), (100, 300.5, 3), (1000, 100, 10), (100, 150, None), (100, 101, None),
])
def test_split_ratio_fingerprint(prev, cur, expected):
    assert matches_split_ratio(prev, cur) == expected


def test_split_ratio_ignores_non_positive_values():
    assert matches_split_ratio(0, 100) is None
    assert matches_split_ratio(100, -5) is None


@pytest.mark.parametrize("value, reference, expected", [
    (5_000_000, 5_000, 1_000), (5_000_000_000, 5_000, 1_000_000),
    (5_100, 5_000, None), (50_000, 5_000, None),
])
def test_scale_error_fingerprint(value, reference, expected):
    assert scale_error_factor(value, reference) == expected


def test_exact_doubling_across_every_ticker_is_flagged():
    prev = {"A": 100, "B": 2_000, "C": 55}
    assert is_doubled(prev, {k: v * 2 for k, v in prev.items()})


def test_ordinary_trading_is_not_flagged_as_doubling():
    prev = {"A": 100, "B": 2_000, "C": 55, "D": 10}
    assert not is_doubled(prev, {"A": 130, "B": 1_700, "C": 60, "D": 11})
    # one position that doubles is trading, not duplication
    assert not is_doubled(prev, {"A": 200, "B": 2_000, "C": 55, "D": 10})


def test_doubling_needs_overlapping_tickers():
    assert not is_doubled({"A": 1}, {"B": 2})


def test_partial_gap_catches_seventy_two_percent_but_not_a_complete_gap():
    assert coverage_ratio(72, 100) == pytest.approx(0.72)
    assert is_partial_gap(72, 100)
    assert not is_partial_gap(0, 100)      # nothing reported is a different, obvious failure
    assert not is_partial_gap(100, 100)
    assert not is_partial_gap(95, 100)


def test_ownership_above_one_hundred_percent():
    assert exceeds_full_ownership(1_100, 1_000)
    assert not exceeds_full_ownership(900, 1_000)
    assert not exceeds_full_ownership(10, 0)
