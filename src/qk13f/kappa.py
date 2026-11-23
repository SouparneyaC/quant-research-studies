"""Common-ownership overlap (kappa) from institutional holdings.

For firms f and g, let beta_fs be the share of firm f held by investor s. With
proportional control (Rotemberg 1984):

    kappa_fg = sum_s(beta_fs * beta_gs) / sum_s(beta_fs ** 2)

The denominator is the investor concentration index of firm f (IHHI_f). The
numerator is how much of firm g the same investors hold, weighted by their
stake in f. A value of 1 means f's owners hold g exactly as they hold f.

Splitting investors into groups gives an additive decomposition:

    kappa_fg = sum_G [ sum_{s in G}(beta_fs * beta_gs) / IHHI_f ]

Every group divides by the same IHHI_f, never by a group-only index. That is
what makes the group contributions sum exactly to kappa_fg.

Reference: Backus, Conlon and Sinkinson (2019), "Common Ownership in America:
1980-2017".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd


def _align(beta_f: pd.Series, beta_g: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    union = beta_f.index.union(beta_g.index)
    return (beta_f.reindex(union, fill_value=0.0).to_numpy(),
            beta_g.reindex(union, fill_value=0.0).to_numpy())


def ihhi(beta: pd.Series) -> float:
    """Investor concentration index of one firm: the sum of squared stakes."""
    return float(np.dot(beta.to_numpy(), beta.to_numpy()))


def calc_kappa(beta_f: pd.Series, beta_g: pd.Series) -> float:
    """kappa_fg for two firms' stakes, each a Series indexed by investor."""
    b_f, b_g = _align(beta_f, beta_g)
    denom = float(np.dot(b_f, b_f))
    return float(np.dot(b_f, b_g) / denom) if denom > 0 else float("nan")


def kappa_contributions(beta_f: pd.Series, beta_g: pd.Series,
                        groups: Mapping[str, str]) -> dict[str, float]:
    """Each investor group's additive share of kappa_fg.

    groups maps an investor to its group label. Investors missing from the map
    fall into the group "other". The values sum to calc_kappa(beta_f, beta_g).
    """
    b_f, b_g = _align(beta_f, beta_g)
    union = beta_f.index.union(beta_g.index)
    denom = float(np.dot(b_f, b_f))
    if denom == 0:
        return {}
    totals: dict[str, float] = {}
    for investor, product in zip(union, b_f * b_g, strict=True):
        label = groups.get(investor, "other")
        totals[label] = totals.get(label, 0.0) + float(product)
    return {label: value / denom for label, value in totals.items()}


def build_beta(holdings_q: pd.DataFrame, shares_q: pd.DataFrame,
               cik_to_parent: Mapping[str, str],
               contam_scale: Mapping[tuple[str, int, int], float],
               year: int, quarter: int, tickers: Iterable[str]) -> dict[str, pd.Series]:
    """Stakes of each investor in each firm for one quarter.

    holdings_q has the columns ticker, filer_cik and shares_held. shares_q has
    ticker and shares (shares outstanding). Filers that share a parent are
    consolidated first. A contamination scale factor, keyed by
    (ticker, year, quarter), multiplies the stakes, and stakes are capped at 1.
    A firm with no holdings or no share count gets an empty Series.
    """
    hq = holdings_q.copy()
    hq["parent"] = hq["filer_cik"].map(cik_to_parent).fillna(hq["filer_cik"])
    hq = hq.groupby(["ticker", "parent"])["shares_held"].sum().reset_index()

    beta: dict[str, pd.Series] = {}
    for ticker in tickers:
        firm = hq[hq.ticker == ticker].set_index("parent")["shares_held"]
        total = shares_q.loc[shares_q.ticker == ticker, "shares"].to_numpy()
        if len(total) == 0 or total[0] == 0 or firm.empty:
            beta[ticker] = pd.Series(dtype=float)
            continue
        scale = contam_scale.get((ticker, year, quarter), 1.0)
        beta[ticker] = (firm / total[0] * scale).clip(upper=1.0)
    return beta
