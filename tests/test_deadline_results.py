"""The committed turnover table agrees with the numbers the deadline-filers README reports."""

from pathlib import Path

import pandas as pd
import pytest

STUDY = Path(__file__).resolve().parents[1] / "studies" / "deadline-filers"


@pytest.fixture(scope="module")
def turnover():
    return pd.read_csv(STUDY / "turnover.csv")


def test_sample_shape(turnover):
    assert len(turnover) == 40
    assert turnover.groupby("fund").size().eq(8).all()
    assert set(turnover["type"]) == {"deadline_hugger", "early_filer"}
    counts = turnover["type"].value_counts()
    assert counts["deadline_hugger"] == 24
    assert counts["early_filer"] == 16


def test_group_means_and_ratio(turnover):
    g = turnover.groupby("type")
    hug, early = g.get_group("deadline_hugger"), g.get_group("early_filer")
    assert hug["turnover_pct"].mean() == pytest.approx(0.3768, abs=0.0001)
    assert early["turnover_pct"].mean() == pytest.approx(0.0809, abs=0.0001)
    assert hug["turnover_pct"].mean() / early["turnover_pct"].mean() == pytest.approx(4.66, abs=0.01)
    assert hug["lag"].mean() == pytest.approx(44.96, abs=0.01)
    assert early["lag"].mean() == pytest.approx(35.69, abs=0.01)
    assert hug["opt_pct"].mean() == pytest.approx(0.6114, abs=0.0001)
    assert early["opt_pct"].max() == 0.0


def test_labels_are_per_fund_not_per_quarter(turnover):
    # README: three fund-quarters sit on the other side of the 43-day line.
    hug_early = (turnover["type"].eq("deadline_hugger") & turnover["lag"].lt(43)).sum()
    early_late = (turnover["type"].eq("early_filer") & turnover["lag"].ge(43)).sum()
    assert (hug_early, early_late) == (2, 1)
    assert turnover["lag"].max() == 54


def test_summary_tables_match_turnover(turnover):
    summary = pd.read_csv(STUDY / "results" / "group_summary.csv").set_index("type")
    for kind, grp in turnover.groupby("type"):
        assert summary.loc[kind, "avg_turnover_pct"] == pytest.approx(grp["turnover_pct"].mean(), abs=0.0001)
        assert summary.loc[kind, "n_fund_quarters"] == len(grp)
