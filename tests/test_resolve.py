from datetime import date

import pytest

from qk13f.resolve import (
    bigram_jaccard,
    build_index,
    lookup,
    make_bigrams,
    preprocess,
)

SECMASTER = """identifier,name,as_of_date,entity_type
q-apple,Apple Inc,2013-03-31,Common Stock
q-amat,Applied Materials Inc,2013-03-31,Common Stock
q-gs,Goldman Sachs Group Inc,2013-03-31,Common Stock
q-gsetf,Goldman Sachs ETF Trust,2013-03-31,ETF
q-newco,Newco Holdings Inc,2020-01-01,Common Stock
"""


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "secmaster.csv"
    path.write_text(SECMASTER, encoding="utf-8")
    return build_index(str(path))


def test_preprocess_expands_abbreviations_and_drops_legal_suffixes():
    assert preprocess("APPLIED MATLS INC") == "applied materials"
    assert preprocess("Applied Materials Inc") == "applied materials"
    assert preprocess("  J.P. Morgan &amp;amp; Co  ") == preprocess("J.P. Morgan & Co")
    assert preprocess("") == ""


def test_bigrams_of_a_truncation_overlap_the_full_name():
    full = make_bigrams(preprocess("AUTOMATIC DATA PROCESSING INC"))
    cut = make_bigrams(preprocess("AUTOMATIC DATA PROCESSING IN"))
    assert bigram_jaccard(full, cut) > 0.9
    assert bigram_jaccard(frozenset(), full) == 0.0


def test_a_misspelled_and_abbreviated_name_resolves(index):
    assert lookup("APPLIED MATLS INC", "2015-06-30", index) == "q-amat"
    assert lookup("Apple Inc", date(2015, 6, 30), index) == "q-apple"


def test_equity_filter_keeps_etfs_out_of_equity_matches(index):
    assert lookup("GOLDMAN SACHS GROUP INC", "2015-06-30", index) == "q-gs"
    assert lookup("GOLDMAN SACHS ETF TR", "2015-06-30", index) != "q-gsetf"


def test_as_of_date_blocks_companies_that_did_not_exist_yet(index):
    assert lookup("NEWCO HOLDINGS", "2015-06-30", index) is None
    assert lookup("NEWCO HOLDINGS", "2021-06-30", index) == "q-newco"


def test_unresolvable_names_return_none_instead_of_a_guess(index):
    assert lookup("ZZZZ QQQQ XXXX", "2015-06-30", index) is None


def test_details_carry_a_confidence_tier(index):
    result = lookup("Apple Inc", "2015-06-30", index, return_details=True)
    assert result["identifier"] == "q-apple"
    assert result["confidence"] in {"high", "medium"}
    assert 0.0 < result["score"] <= 1.0
