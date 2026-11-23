"""Checks that flag known failure patterns in vendor holdings data.

Each function encodes a pattern found while cleaning 13F and XBRL data from a
data vendor. Each is a test for a signature, not a repair: it says "this looks
like X", and a person decides what to do. The failures and how each was found
are in studies/common-ownership/docs/data-quality.md.

    matches_split_ratio     a share count restated after a stock split
    scale_error_factor      a value reported 1,000 or 1,000,000 times too large
    is_doubled              an original filing and its amendment summed together
    coverage_ratio          how much of the expected holdings a filer reports
    is_partial_gap          a filer reporting some, but not all, of its holdings
    exceeds_full_ownership  institutions holding more than 100% of a company
"""

from __future__ import annotations

from collections.abc import Mapping

KNOWN_SPLITS = (2, 3, 4, 5, 10, 20)
SCALE_FACTORS = (1_000, 1_000_000)


def matches_split_ratio(prev_shares: float, cur_shares: float,
                        splits: tuple[int, ...] = KNOWN_SPLITS,
                        tol: float = 0.02) -> int | None:
    """The split ratio that the quarter-over-quarter change matches, else None.

    A 10-K filed after a split restates shares outstanding for earlier quarters.
    The tell is that adjacent quarters differ by exactly the split ratio.
    """
    if prev_shares <= 0 or cur_shares <= 0:
        return None
    ratio = cur_shares / prev_shares
    for factor in splits:
        if abs(ratio - factor) / factor <= tol or abs(1 / ratio - factor) / factor <= tol:
            return factor
    return None


def scale_error_factor(value: float, reference: float,
                       factors: tuple[int, ...] = SCALE_FACTORS,
                       tol: float = 0.25) -> int | None:
    """The factor by which value exceeds a neighbouring reference, else None.

    A units error in XBRL reports a number 1,000 or 1,000,000 times too large.
    The reference is the same quantity in an adjacent quarter.
    """
    if value <= 0 or reference <= 0:
        return None
    ratio = value / reference
    for factor in factors:
        if abs(ratio - factor) / factor <= tol:
            return factor
    return None


def is_doubled(prev: Mapping[str, float], cur: Mapping[str, float],
               tol: float = 0.02, min_share: float = 0.95) -> bool:
    """True when nearly every ticker's holdings exactly doubled for one filer.

    An original filing and a later amendment can both be ingested and summed.
    Real trading does not double every position at once. prev and cur map a
    ticker to the filer's shares in two adjacent quarters.
    """
    common = [t for t in cur if t in prev and prev[t] > 0]
    if not common:
        return False
    doubled = sum(1 for t in common if abs(cur[t] / prev[t] - 2.0) <= 2.0 * tol)
    return doubled / len(common) >= min_share


def coverage_ratio(observed: float, expected: float) -> float:
    """Observed holdings as a share of the expected level."""
    return observed / expected if expected > 0 else float("nan")


def is_partial_gap(observed: float, expected: float, threshold: float = 0.9) -> bool:
    """True when a filer reports some of its holdings, but well under the expected level.

    A complete gap (nothing reported) is obvious. A partial gap, such as 72% of
    the expected level for two quarters, passes a quick look and needs this
    explicit ratio check. A complete gap returns False.
    """
    ratio = coverage_ratio(observed, expected)
    return 0.0 < ratio < threshold


def exceeds_full_ownership(institutional_shares: float, shares_outstanding: float) -> bool:
    """True when institutions hold more than 100% of a company's shares.

    Usually a sign of convertible-bond holdings reported with equity, which
    calls for a scale factor and not for dropping the quarter.
    """
    return shares_outstanding > 0 and institutional_shares > shares_outstanding
