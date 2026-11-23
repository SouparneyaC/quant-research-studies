"""
test_statestreet_lookup.py
==========================
Validates the fuzzy name lookup function against real State Street
Q2/Q3 2015 EDGAR data, the exact filing where QK lost ~240 rows.

WHAT THIS TESTS
---------------
State Street's Q2 and Q3 2015 13F filings contain 608 CUSIPs shorter
than 9 digits, a result of integer coercion stripping leading zeros, or
numbers being stored as scientific notation (e.g. "876E110" for TARGET CORP).

  500 can be repaired by check-digit padding  → already handled
  108 cannot be padded → these are what we test here:
    97 scientific notation CUSIPs (unrecoverable by padding)
    11 structurally unresolvable CUSIPs

For each of these 108 rows, we have the company name the filer typed.
The lookup function takes that name + the filing date and tries to find
the correct CUSIP (proxy for QKID in our test) from the reference corpus.

HOW TO READ THE RESULTS
-----------------------
  RESOLVED: function returned a match above threshold. We show whether
               the match is CORRECT (right company) or WRONG (false positive).
  NULL: function returned None. Either the company is foreign/delisted
               and genuinely missing from the reference, or the name is
               too corrupted/ambiguous to match.

EXPECTED OUTCOME
----------------
  Not all 108 will resolve, foreign companies (VALE SA, BT GROUP PLC)
  and acquired companies (DYAX CORP, acquired 2016) may be missing
  from the SEC 13F list we use as a stand-in for QuantKiosk's secmaster.
  With QuantKiosk's full 60k-row secmaster those would likely resolve.

HOW TO RUN
----------
  python3 scripts/test_statestreet_lookup.py
"""

import os, re, sys
import pandas as pd
from datetime import date

# Add scripts directory to path so we can import the lookup module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fuzzy_name_lookup import (
    build_index_from_sec13f_list,
    build_index,
    lookup,
    preprocess,
    make_bigrams,
    bigram_jaccard,
    load_index,
)

BASE     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "..", "data")

SEC13F_PATH  = os.path.join(DATA_DIR, "sec_13f_official_list.csv")
AUDIT_PATH   = os.path.join(DATA_DIR, "audit_statestreet_2015_edgar_positions.csv")
REF_PATH     = os.path.join(DATA_DIR, "cusip_reference_74tickers.csv")
INDEX_PATH   = os.path.join(DATA_DIR, "fuzzy_lookup_index.pkl")
RESULTS_PATH = os.path.join(DATA_DIR, "statestreet_lookup_results.csv")


# =============================================================================
# STEP 1: IDENTIFY THE 108 ROWS THAT NEED NAME-BASED LOOKUP
# These are the rows where CUSIP padding fails. The ones that motivated
# this entire second-mapping-path effort.
# =============================================================================

def cusip_check_digit(c8: str) -> str:
    """CUSIP check digit algorithm (Modulus 10)."""
    total = 0
    for i, c in enumerate(c8.upper()):
        v = int(c) if c.isdigit() else (ord(c) - ord('A') + 10)
        if i % 2 == 1: v *= 2
        total += v // 10 + v % 10
    return str((10 - total % 10) % 10)

def classify_cusip(cusip_str: str):
    """
    Returns ('padded', repaired_cusip) if fixable,
            ('sci_notation', None) if scientific notation,
            ('unresolvable', None) if neither works.
    """
    c = str(cusip_str).strip()
    if re.search(r'[Ee]', c):
        return 'sci_notation', None
    for n in range(1, 4):
        candidate = '0' * n + c
        if len(candidate) == 9:
            if cusip_check_digit(candidate[:8]) == candidate[8]:
                return 'padded', candidate
    return 'unresolvable', None


def load_state_street_failures():
    """
    Load the 108 rows from State Street Q2/Q3 2015 that cannot be
    fixed by CUSIP padding, the target of the name-based second pass.
    """
    audit = pd.read_csv(AUDIT_PATH)
    audit['cusip_str'] = audit['cusip'].astype(str).str.strip()

    failures = []
    for _, row in audit.iterrows():
        method, repaired = classify_cusip(row['cusip_str'])
        if method in ('sci_notation', 'unresolvable'):
            failures.append({
                'name':           row['name'],
                'original_cusip': row['cusip_str'],
                'method':         method,
                'quarter':        row['quarter_label'],
                'filing_date':    '2015-06-30' if row['quarter_label'] == 'Q2-2015'
                                  else '2015-09-30',
            })

    df = pd.DataFrame(failures).drop_duplicates('original_cusip')
    return df


# =============================================================================
# STEP 2: BUILD THE REFERENCE INDEX
# We use the SEC 13F official list (24k securities) as a stand-in for
# QuantKiosk's 60k-row secmaster. The logic is identical, QuantKiosk's version
# would simply have more entries and real QKIDs instead of CUSIPs.
# =============================================================================

def build_reference_index():
    """
    Build bigram index from the SEC 13F official list.
    Saved to disk so subsequent runs are fast.

    For each entry in the SEC list:
      - identifier = CUSIP (proxy for QKID in this test)
      - name = company_name from SEC list
      - as_of_date = 2013-12-31 (start of QK coverage, conservative)
      - entity_type = security_type from SEC list

    In QuantKiosk's production version, the secmaster would contain real QKIDs
    and proper as-of dates per entity. The logic is identical.
    """
    if os.path.exists(INDEX_PATH):
        print(f"Loading cached index from {INDEX_PATH}...")
        return load_index(INDEX_PATH)

    print("Building bigram index from SEC 13F official list...")
    index = build_index_from_sec13f_list(
        SEC13F_PATH,
        as_of_date="20131231",
        save_path=INDEX_PATH
    )
    return index


# =============================================================================
# STEP 3: RUN THE LOOKUP AND EVALUATE
# For each of the 108 failing rows, run the fuzzy name lookup and
# report what we got.
#
# Since we do not have ground-truth QKIDs for these rows, we evaluate
# match quality by checking whether the returned name is plausibly the
# correct company. A match is CORRECT if the returned company name
# clearly corresponds to the original name. WRONG means false positive.
# =============================================================================

def evaluate_match(original_name: str, matched_name: str | None) -> str:
    """
    Rough correctness check: are these clearly the same company?
    Uses token overlap, if the match shares 2+ meaningful tokens, it is
    probably correct. This is for human-readable reporting, not production.
    """
    if not matched_name:
        return "NULL"

    STOP = {"inc", "corp", "co", "ltd", "the", "new", "com", "cos"}
    def toks(s):
        return set(re.sub(r'[^\w\s]', ' ', s.lower()).split()) - STOP

    orig_toks    = toks(original_name)
    matched_toks = toks(matched_name)
    overlap      = len(orig_toks & matched_toks)

    if overlap >= 2:
        return "CORRECT"
    elif overlap == 1 and len(orig_toks) <= 2:
        return "LIKELY"
    else:
        return "WRONG"


def run_test():
    print("=" * 65)
    print("STATE STREET Q2/Q3 2015, FUZZY NAME LOOKUP TEST")
    print("=" * 65)

    # Load data
    failures = load_state_street_failures()
    print(f"\nTarget rows (unpaddable CUSIPs): {len(failures)}")
    print(f"  Sci-notation:  {(failures['method']=='sci_notation').sum()}")
    print(f"  Unresolvable:  {(failures['method']=='unresolvable').sum()}")

    # Build index
    index = build_reference_index()
    n_entries = len(index["entries"])
    n_bigrams = len(index["inverted"])
    print(f"\nIndex: {n_entries:,} entries, {n_bigrams:,} unique bigrams")

    # Run lookup
    print("\nRunning lookup...")
    results = []
    for _, row in failures.iterrows():
        detail = lookup(
            raw_name     = row['name'],
            filing_date  = row['filing_date'],
            index        = index,
            threshold    = 0.30,
            return_details=True
        )

        if detail:
            verdict = evaluate_match(row['name'], detail['name'])
            results.append({
                'original_name':   row['name'],
                'original_cusip':  row['original_cusip'],
                'method':          row['method'],
                'quarter':         row['quarter'],
                'matched_name':    detail['name'],
                'matched_id':      detail['identifier'],
                'score':           detail['score'],
                'entity_type':     detail['entity_type'],
                'verdict':         verdict,
            })
        else:
            results.append({
                'original_name':   row['name'],
                'original_cusip':  row['original_cusip'],
                'method':          row['method'],
                'quarter':         row['quarter'],
                'matched_name':    None,
                'matched_id':      None,
                'score':           0.0,
                'entity_type':     None,
                'verdict':         'NULL',
            })

    df = pd.DataFrame(results)
    df.to_csv(RESULTS_PATH, index=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("RESULTS")
    print("=" * 65)

    correct   = (df['verdict'] == 'CORRECT').sum()
    likely    = (df['verdict'] == 'LIKELY').sum()
    wrong     = (df['verdict'] == 'WRONG').sum()
    null      = (df['verdict'] == 'NULL').sum()
    total     = len(df)

    print(f"\nTotal rows tested:   {total}")
    print(f"CORRECT matches:     {correct}  ({correct/total*100:.1f}%)")
    print(f"LIKELY correct:      {likely}   ({likely/total*100:.1f}%)")
    print(f"WRONG (false pos):   {wrong}   ({wrong/total*100:.1f}%)")
    print(f"NULL (no match):     {null}  ({null/total*100:.1f}%)")
    print()

    resolved = correct + likely
    print(f"Resolution rate:     {resolved}/{total} = {resolved/total*100:.1f}%")
    print(f"  (with QuantKiosk's 60k secmaster this would be higher , ")
    print(f"   SEC 13F list has ~6k primary equities vs QuantKiosk's ~60k entries)")

    # ── Correct matches, show them ───────────────────────────────────────────
    print()
    print("─" * 65)
    print("CORRECT MATCHES (sample)")
    print("─" * 65)
    correct_df = df[df['verdict'].isin(['CORRECT','LIKELY'])].head(15)
    for _, r in correct_df.iterrows():
        print(f"  [{r['score']:.2f}] \"{r['original_name']}\"")
        print(f"         → \"{r['matched_name']}\"  ({r['entity_type']})")
        print()

    # ── Wrong matches, false positives ───────────────────────────────────────
    wrong_df = df[df['verdict'] == 'WRONG']
    if len(wrong_df):
        print("─" * 65)
        print("FALSE POSITIVES (wrong match returned)")
        print("─" * 65)
        for _, r in wrong_df.iterrows():
            print(f"  [{r['score']:.2f}] \"{r['original_name']}\"")
            print(f"         → \"{r['matched_name']}\"  ← WRONG")
            print()

    # ── Null, genuinely unresolvable ─────────────────────────────────────────
    null_df = df[df['verdict'] == 'NULL']
    if len(null_df):
        print("─" * 65)
        print("NULL RETURNS (no match above threshold)")
        print("─" * 65)
        print("  These are likely: foreign companies, delisted pre-coverage,")
        print("  or companies too small for the SEC 13F equity list.")
        print()
        for _, r in null_df.head(15).iterrows():
            print(f"  \"{r['original_name']}\"  "
                  f"(original CUSIP: {r['original_cusip']})")

    # ── What QuantKiosk's secmaster would improve ───────────────────────────────────
    print()
    print("─" * 65)
    print("NOTE ON TEST LIMITATIONS")
    print("─" * 65)
    print(f"  We tested against the SEC 13F official list (~6k primary")
    print(f"  equities). QuantKiosk's secmaster has ~60k entity-instrument rows")
    print(f"  covering international securities, ETFs, and historical entries.")
    print(f"  The NULL rate would shrink significantly with the full master.")
    print()
    print(f"Full results saved → {RESULTS_PATH}")

    return df


if __name__ == "__main__":
    run_test()
