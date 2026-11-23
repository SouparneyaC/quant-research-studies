"""
SCRIPT: audit_statestreet_2015_edgar_vs_qk.py
==============================================
PURPOSE
-------
Audits QUANTkiosk (QK) 13(f) data against SEC EDGAR ground truth for
State Street Corporation (CIK 93751), Q2 and Q3 of 2015.

QK reported a ~28% drop in State Street's total holdings in those two
quarters, which is not economically plausible for a passive index manager.
This script downloads the original 13(f) workbook XML files directly from
EDGAR, parses every position, and compares them to what QK actually stored
in our local holdings CSVs, to confirm whether the data gap is in the SEC
filing itself or in QK's ingestion pipeline.

FINDINGS (documented at bottom of this file)

INPUTS
------
- SEC EDGAR 13(f) workbook XMLs (fetched live, no API key needed)
    Q2 2015 accession: 0000093751-15-000188
    Q3 2015 accession: 0000093751-15-000232
- Local QK holdings CSVs (all four batches)

OUTPUT
------
Prints a ticker-level comparison table to stdout.
Saves full EDGAR position list to:
    data/audit_statestreet_2015_edgar_positions.csv
"""

import os, re, ssl, urllib.request
import certifi
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "..", "data")

# Holdings CSVs pulled from QK (all available batches)
QK_HOLDINGS_FILES = [
    os.path.join(DATA_DIR, "holdings_9firms_replication.csv"),
    os.path.join(DATA_DIR, "holdings_10firms_batch2.csv"),
    os.path.join(DATA_DIR, "holdings_10firms_batch3.csv"),
    os.path.join(DATA_DIR, "holdings_sp500_universe.csv"),
]

STATE_STREET_CIK = "93751"

# The two affected quarters
AFFECTED = [
    # (label, filing_accession_no_dashes, workbook_xml_filename)
    ("Q2-2015", "000009375115000188", "a13fworkbook1.xml"),
    ("Q3-2015", "000009375115000232", "a13fworkbookq32015.xml"),
    # Note: Q3 uses a different filename, this itself may be a clue for QK,
    # as a parser hardcoded to "a13fworkbook1.xml" would silently return 404
    # and produce zero rows for Q3 2015 specifically.
]

# ── EDGAR fetch helpers ────────────────────────────────────────────────────────

# EDGAR requires a User-Agent header identifying the caller.
# See: https://www.sec.gov/developer
EDGAR_HEADERS = {"User-Agent": "academic-research " + os.environ.get("SEC_CONTACT_EMAIL", "contact@example.com")}

# Verify certificates with the certifi bundle.
SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def fetch_url(url: str) -> str:
    """Download URL text content from SEC EDGAR."""
    req = urllib.request.Request(url, headers=EDGAR_HEADERS)
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return r.read().decode()


def parse_13f_workbook(xml: str) -> pd.DataFrame:
    """
    Parse a 13(f) workbook XML and return one row per <infoTable> entry.

    Each <infoTable> is a single line item in the filing, one security,
    one manager attribution. The same issuer can appear in multiple
    <infoTable> blocks when positions are split across subsidiary managers
    (e.g., SSGA Funds Management vs State Street Bank & Trust Co).
    Those must be summed to get the filer's total position in that issuer.

    Returns columns: name, cusip, shares, value_k, manager_tag
    """
    blocks = re.findall(r'<infoTable>(.*?)</infoTable>', xml, re.DOTALL)
    rows = []
    for b in blocks:
        name   = re.search(r'<nameOfIssuer>(.*?)</nameOfIssuer>',  b)
        cusip  = re.search(r'<cusip>(.*?)</cusip>',                b)
        shares = re.search(r'<sshPrnamt>(.*?)</sshPrnamt>',        b)
        value  = re.search(r'<value>(.*?)</value>',                b)
        mgr    = re.search(r'<otherManager>(.*?)</otherManager>',  b)
        if name and shares:
            rows.append({
                "name":        name.group(1).strip(),
                "cusip":       cusip.group(1).strip() if cusip else "",
                "shares":      int(shares.group(1)),
                "value_k":     int(value.group(1)) if value else 0,
                # manager_tag is a comma-separated list of subsidiary manager
                # sequence numbers whose assets are covered by this row.
                # Sequence numbers map back to the <otherManagers2Info> block
                # in the cover page XML (primary_doc.xml).
                "manager_tag": mgr.group(1).strip() if mgr else "PRIMARY",
            })
    return pd.DataFrame(rows)


# ── Step 1: Load QK holdings for State Street, Q2 and Q3 2015 ─────────────────

print("Loading QK holdings data...")

frames = []
for path in QK_HOLDINGS_FILES:
    if os.path.exists(path):
        df = pd.read_csv(path, dtype={"filer_cik": str})
        df["filer_cik"] = df["filer_cik"].str.replace(r"\.0$", "", regex=True).str.strip()
        frames.append(df)
        print(f"  loaded: {os.path.basename(path):45s} ({len(df):,} rows)")

h = pd.concat(frames, ignore_index=True)
ss = h[h["filer_cik"] == STATE_STREET_CIK]

# Build per-ticker share totals for each quarter of interest (and anchor quarters)
def qk_totals(year, qtr):
    return (ss[(ss["year"] == year) & (ss["quarter"] == qtr)]
            .groupby("ticker")["shares_held"].sum()
            .rename(f"qk_{year}q{qtr}"))

qk_q1 = qk_totals(2015, 1)
qk_q2 = qk_totals(2015, 2)
qk_q3 = qk_totals(2015, 3)
qk_q4 = qk_totals(2015, 4)

print(f"\nState Street rows in QK, "
      f"Q1:{((ss.year==2015)&(ss.quarter==1)).sum()} "
      f"Q2:{((ss.year==2015)&(ss.quarter==2)).sum()} "
      f"Q3:{((ss.year==2015)&(ss.quarter==3)).sum()} "
      f"Q4:{((ss.year==2015)&(ss.quarter==4)).sum()}")


# ── Step 2: Download and parse EDGAR ground-truth workbooks ───────────────────

edgar_totals = {}

for label, accession, workbook_file in AFFECTED:
    url = (f"https://www.sec.gov/Archives/edgar/data/{STATE_STREET_CIK}"
           f"/{accession}/{workbook_file}")
    print(f"\nFetching EDGAR {label} workbook: {workbook_file}")
    xml  = fetch_url(url)
    df   = parse_13f_workbook(xml)
    print(f"  Parsed {len(df):,} <infoTable> entries "
          f"covering {df['name'].nunique():,} unique issuers")

    # Save the raw EDGAR parse for reference
    df["quarter_label"] = label
    edgar_totals[label] = df

# Combine both quarters and save to disk for reference
edgar_all = pd.concat(edgar_totals.values(), ignore_index=True)
out_path = os.path.join(DATA_DIR, "audit_statestreet_2015_edgar_positions.csv")
edgar_all.to_csv(out_path, index=False)
print(f"\nSaved full EDGAR position list → {out_path}")

# Roll up to issuer-level totals (sum across subsidiary manager rows)
edgar_q2_totals = (edgar_totals["Q2-2015"]
                   .groupby("name")["shares"].sum()
                   .rename("edgar_q2"))
edgar_q3_totals = (edgar_totals["Q3-2015"]
                   .groupby("name")["shares"].sum()
                   .rename("edgar_q3"))

edgar_by_name = pd.concat([edgar_q2_totals, edgar_q3_totals], axis=1).fillna(0).astype(int)


# ── Step 3: Join QK tickers to EDGAR issuers via keyword match ────────────────
#
# QK data uses tickers (AAPL, BAC …) while EDGAR uses issuer name strings
# ("APPLE INC", "BANK OF AMERICA CORP …"). We bridge with a manual keyword map.

TICKER_KEYWORDS = {
    "A":    "AGILENT",        "ABBV": "ABBVIE",          "ABT":  "ABBOTT",
    "ACN":  "ACCENTURE",      "ADBE": "ADOBE",           "ADI":  "ANALOG DEVICES",
    "ADM":  "ARCHER",         "ADP":  "AUTOMATIC DATA",  "ADSK": "AUTODESK",
    "AEE":  "AMEREN",         "AEP":  "AMERICAN ELECTRIC","AFL": "AFLAC",
    "AIG":  "AMERICAN INTL",  "ALL":  "ALLSTATE",        "AMAT": "APPLIED MATERIALS",
    "AME":  "AMETEK",         "AMZN": "AMAZON",          "AAL":  "AMERICAN AIRLINES",
    "AAPL": "APPLE",          "BAC":  "BANK OF AMER",    "DAL":  "DELTA AIR",
    "JPM":  "JPMORGAN",       "KO":   "COCA-COLA",       "MA":   "MASTERCARD",
    "META": "META",           "MRK":  "MERCK",           "MSFT": "MICROSOFT",
    "NFLX": "NETFLIX",        "NVDA": "NVIDIA",          "PFE":  "PFIZER",
    "TGT":  "TARGET",
}


# ── Step 4: Build and print comparison table ──────────────────────────────────

print("\n" + "="*110)
print("STATE STREET (CIK 93751), EDGAR GROUND TRUTH vs QK REPORTED HOLDINGS, Q2 and Q3 2015")
print("="*110)
print(f"{'Ticker':<6} {'QK Q1':>13} {'EDGAR Q2':>13} {'QK Q2':>13} {'Missing Q2':>13}"
      f" {'EDGAR Q3':>13} {'QK Q3':>13} {'Missing Q3':>13}  Status")
print("-"*110)

summary = []
for ticker in sorted(TICKER_KEYWORDS):
    kw   = TICKER_KEYWORDS[ticker]
    mask = edgar_by_name.index.str.contains(kw, case=False)
    e2   = int(edgar_by_name.loc[mask, "edgar_q2"].sum())
    e3   = int(edgar_by_name.loc[mask, "edgar_q3"].sum())

    q1  = int(qk_q1.get(ticker, 0))
    q2  = int(qk_q2.get(ticker, 0))
    q3  = int(qk_q3.get(ticker, 0))

    if e2 == 0 and e3 == 0:
        continue    # State Street doesn't hold this ticker at all; skip

    miss2  = e2 - q2
    miss3  = e3 - q3

    if q2 == 0 and e2 > 0:
        status = "COMPLETELY MISSING"
    elif miss2 > 0:
        status = "PARTIAL MISS"
    else:
        status = "OK"

    print(f"{ticker:<6} {q1:>13,} {e2:>13,} {q2:>13,} {miss2:>13,}"
          f" {e3:>13,} {q3:>13,} {miss3:>13,}  {status}")
    summary.append({"ticker": ticker, "edgar_q2": e2, "qk_q2": q2, "miss_q2": miss2,
                    "edgar_q3": e3, "qk_q3": q3, "miss_q3": miss3, "status": status})

df_summary = pd.DataFrame(summary)
print("-"*110)
total_miss_q2 = df_summary["miss_q2"].sum()
total_miss_q3 = df_summary["miss_q3"].sum()
print(f"{'TOTAL':6} {'':>13} {'':>13} {'':>13} {total_miss_q2:>13,}"
      f" {'':>13} {'':>13} {total_miss_q3:>13,}")

print()
by_status = df_summary["status"].value_counts()
print(f"  Completely missing : {by_status.get('COMPLETELY MISSING', 0):>3} tickers")
print(f"  Partially missing  : {by_status.get('PARTIAL MISS', 0):>3} tickers")
print(f"  Correctly reported : {by_status.get('OK', 0):>3} tickers")


# =============================================================================
# FINDINGS AND ROOT CAUSE ANALYSIS
# =============================================================================
#
# WHAT WE FOUND
# -------------
# State Street's Q2 and Q3 2015 data in QK is severely incomplete.
# Across our 31 tracked tickers, QK is missing over 1 billion shares per quarter
# that are clearly documented in the SEC EDGAR filing.
#
#   Q2 2015: ~1.016 billion shares missing from QK
#   Q3 2015: ~1.014 billion shares missing from QK
#
# The two largest gaps:
#   BAC: 426,947,954 shares missing in Q2 (QK shows 0; EDGAR shows 426M)
#   AAPL: 232,156,838 shares missing in Q2 (QK shows 0; EDGAR shows 232M)
#
#
# IS THIS A MISSING AMENDMENT?
# ----------------------------
# No. We checked EDGAR's quarterly filing index for all of 2015 and early 2016.
# State Street filed exactly ONE 13(f) per quarter, no 13(f)/A amendments exist
# for Q2 or Q3 2015. The data is in the original filing.
#
#   EDGAR filing index confirms:
#     Q2 2015: 13F-HR filed 2015-08-13, accession 0000093751-15-000188
#     Q3 2015: 13F-HR filed 2015-11-16, accession 0000093751-15-000232
#     (no /A amendment filed for either quarter)
#
#
# IS THIS A FILING ERROR BY STATE STREET?
# ----------------------------------------
# No. The EDGAR cover pages show consistent entry counts and portfolio values:
#
#   Q4 2014: 3,704 entries, $1,004B total value
#   Q1 2015: 3,680 entries,   $974B total value
#   Q2 2015: 3,720 entries,   $936B total value   ← data present, QK is wrong
#   Q3 2015: 3,724 entries,   $859B total value   ← data present, QK is wrong
#   Q4 2015: 3,722 entries,   $915B total value
#
# Entry counts are stable (~3,700) throughout. The value decline in Q3 is the
# broad S&P 500 correction of summer 2015 (normal). State Street filed correctly.
#
#
# MOST LIKELY ROOT CAUSE: QK INGESTION BUG
# ------------------------------------------
# One strong clue: the Q3 2015 workbook uses a different filename than Q2:
#
#   Q2: a13fworkbook1.xml        ← standard name
#   Q3: a13fworkbookq32015.xml   ← non-standard, quarter-specific name
#
# If QK's EDGAR ingestion pipeline hardcoded the filename "a13fworkbook1.xml"
# (or looked for it via a glob pattern that didn't match the Q3 variant), it
# would return a 404 for Q3 2015 and produce zero rows, exactly what we see.
# For Q2, the filename matches, but a different bug (CUSIP de-duplication or a
# subsidiary-manager filtering issue) caused selective drop of some issuers.
#
# Supporting evidence for Q2: tickers with multiple <infoTable> rows (AAPL has 3,
# BAC has 2, KO has 4) are disproportionately represented among the missing/partial
# tickers. If QK's CUSIP de-duplication logic only kept one row per CUSIP and
# discarded the rest, it could silently drop entire positions.
#
# Note: the manager_tag field in each <infoTable> row is a comma-separated list
# of subsidiary manager sequence numbers (not a simple primary/secondary flag).
# This tagging is consistent across missing and non-missing tickers, so it does
# NOT appear to be the cause.
#
#
# WHAT THIS MEANS FOR OUR κ ANALYSIS
# ------------------------------------
# The data gap directly understates State Street's β (ownership share) in
# Q2 and Q3 2015, which in turn understates their κ contribution for those two
# quarters. This shows up as a symmetric dip/spike in the decomposition chart.
#
# Fix applied in: decompose_kappa_by_investor_type.py and compute_kappa.py
#   → Per-ticker linear interpolation using Q1 and Q4 2015 as anchors.
#   → Q2 = (2/3)*Q1 + (1/3)*Q4,  Q3 = (1/3)*Q1 + (2/3)*Q4
#   → Drops the incomplete QK rows and replaces with interpolated values.
#
#
# WHAT TO TELL JEFF (QUANTkiosk)
# --------------------------------
# State Street Corp (CIK 93751), Q2 2015 (accession 0000093751-15-000188)
# and Q3 2015 (accession 0000093751-15-000232).
#
# The SEC filings are complete and correct. Your system is returning incomplete
# data for those two quarters. Specific symptoms:
#
#   1. ~18 tickers show zero shares for State Street in Q2 and Q3, including
#      AAPL (should be ~232M shares) and BAC (should be ~427M shares).
#   2. KO shows ~162M shares in your data but ~172M in EDGAR (partial miss).
#   3. Tickers like MSFT, JPM, PFE are correct in your data.
#
# Suggested investigation:
#   (a) Check whether your Q3 2015 parser found the workbook at the non-standard
#       filename "a13fworkbookq32015.xml" rather than "a13fworkbook1.xml".
#   (b) Check your CUSIP de-duplication logic for Q2 2015, issuers with multiple
#       <infoTable> rows (AAPL, BAC, KO) are disproportionately affected.
#   (c) Run a total-shares reconciliation against the cover page's
#       <tableEntryTotal> and <tableValueTotal> fields as a QA check on ingestion.
#
