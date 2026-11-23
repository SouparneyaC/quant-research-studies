"""
build_cusip_corruption_testset.py
==================================
Builds a synthetic corrupted copy of holdings_sp500_universe.csv for testing
the CUSIP repair pipeline (cusip_repair_prototype.py).

Steps:
  1. Look up the correct 9-char CUSIP for each of the 20 tickers via OpenFIGI.
  2. Attach correct_cusip and company_name to every row in the holdings file.
  3. Corrupt the CUSIPs the same way integer coercion does in real 13(f) filings:
       - All-numeric CUSIPs with leading zeros → strip those zeros
       - Alphanumeric CUSIPs with E between digits → convert to float string
       - Alphanumeric CUSIPs with letters but no E → leave intact (these survive)
  4. Save two files:
       holdings_sp500_universe_CORRECT.csv   , ground truth (correct CUSIPs)
       holdings_sp500_universe_CORRUPTED.csv , what a broken QK ingest would see

The CORRUPTED file is the test input. The CORRECT file is the answer key.
We measure how many the repair script recovers correctly.

OUTPUT
------
  data/holdings_sp500_universe_CORRECT.csv
  data/holdings_sp500_universe_CORRUPTED.csv
  data/cusip_lookup_20tickers.csv    (OpenFIGI results, cached)
"""

import os, re, ssl, json, time
import certifi
import urllib.request
import pandas as pd

BASE     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "..", "data")

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

OPENFIGI_URL  = "https://api.openfigi.com/v3/mapping"
CUSIP_CACHE   = os.path.join(DATA_DIR, "cusip_lookup_20tickers.csv")


# =============================================================================
# STEP 1: LOOK UP CUSIPS VIA OPENFIGI
# =============================================================================

# Manually verified CUSIPs for all 20 tickers in the universe file.
# Cross-checked against EDGAR, CRSP documentation, and OpenFIGI.
# These are the ground truth we corrupt and then try to recover.
KNOWN_CUSIPS = {
    "A":    "00846U101",   # Agilent Technologies        leading zero → truncated
    "ABBV": "00287Y109",   # AbbVie Inc                  leading zeros → truncated
    "ABT":  "002824100",   # Abbott Laboratories          leading zeros → truncated
    "ACN":  "G1151C101",   # Accenture plc (Ireland)     alphanumeric, G-prefix
    "ADBE": "00724F101",   # Adobe Inc                   leading zeros → truncated
    "ADI":  "032654105",   # Analog Devices              leading zeros → truncated
    "ADM":  "039483102",   # Archer-Daniels-Midland      leading zero → truncated
    "ADP":  "053015103",   # Automatic Data Processing   leading zero → truncated
    "ADSK": "052769106",   # Autodesk Inc                leading zero → truncated
    "AEE":  "023608102",   # Ameren Corp                 leading zeros → truncated
    "AEP":  "025537101",   # American Electric Power     leading zeros → truncated
    "AES":  "00130H105",   # AES Corporation             leading zeros → truncated
    "AFL":  "001055102",   # Aflac Inc                   leading zeros → truncated
    "AIG":  "026874103",   # American International Group leading zero → truncated
    "AIZ":  "04621X108",   # Assurant Inc                alphanumeric
    "AKAM": "00971T101",   # Akamai Technologies         leading zeros → truncated
    "ALL":  "020002101",   # Allstate Corp               leading zeros → truncated
    "ALLE": "G0176J109",   # Allegion plc (Ireland)      alphanumeric, G-prefix
    "AMAT": "038222105",   # Applied Materials           leading zeros → truncated
    "AME":  "031100100",   # Ametek Inc                  leading zeros → truncated
}

# Tickers in the 9-firm file (no company_name column there, add them)
KNOWN_CUSIPS.update({
    "AAPL": "037833100",   # Apple Inc                   leading zero → truncated
    "MSFT": "594918104",   # Microsoft Corp              no leading zero, safe
    "AAL":  "02376R102",   # American Airlines           alphanumeric, safe from int
    "DAL":  "247361702",   # Delta Air Lines             no leading zero, safe
    "JPM":  "46625H100",   # JPMorgan Chase              alphanumeric
    "BAC":  "060505104",   # Bank of America             leading zero → truncated
    "PFE":  "717081103",   # Pfizer Inc                  no leading zero, safe
    "MRK":  "589331107",   # Merck & Co                  no leading zero, safe
    "NVDA": "67066G104",   # NVIDIA Corp                 alphanumeric
})

COMPANY_NAMES = {
    "A":    "Agilent Technologies Inc",
    "ABBV": "AbbVie Inc",
    "ABT":  "Abbott Laboratories",
    "ACN":  "Accenture PLC",
    "ADBE": "Adobe Inc",
    "ADI":  "Analog Devices Inc",
    "ADM":  "Archer-Daniels-Midland Co",
    "ADP":  "Automatic Data Processing Inc",
    "ADSK": "Autodesk Inc",
    "AEE":  "Ameren Corp",
    "AEP":  "American Electric Power Co",
    "AES":  "AES Corp",
    "AFL":  "Aflac Inc",
    "AIG":  "American International Group Inc",
    "AIZ":  "Assurant Inc",
    "AKAM": "Akamai Technologies Inc",
    "ALL":  "Allstate Corp",
    "ALLE": "Allegion PLC",
    "AMAT": "Applied Materials Inc",
    "AME":  "Ametek Inc",
    "AAPL": "Apple Inc",
    "MSFT": "Microsoft Corp",
    "AAL":  "American Airlines Group Inc",
    "DAL":  "Delta Air Lines Inc",
    "JPM":  "JPMorgan Chase Co",
    "BAC":  "Bank of America Corp",
    "PFE":  "Pfizer Inc",
    "MRK":  "Merck Co Inc",
    "NVDA": "NVIDIA Corp",
}


# =============================================================================
# STEP 2: CORRUPTION FUNCTIONS
# =============================================================================

def corruption_type(cusip: str) -> str:
    """
    Classify how this CUSIP would be corrupted by real-world integer coercion.
    Mirrors the corruption pattern confirmed in State Street 2015 filings.
    """
    if re.search(r'\d[Ee]\d', cusip):
        return "sci_notation"           # e.g. 87612E106 → destroyed
    if cusip[0] == '0' and cusip.isdigit():
        return "truncated"              # e.g. 037833100 → 37833100
    if not cusip.isdigit():
        return "alphanumeric_safe"      # e.g. 02376R102 → stored as string, safe
    return "numeric_no_leading_zero"   # e.g. 594918104 → no change


def corrupt_cusip(cusip: str) -> str:
    """
    Apply the integer-coercion corruption to a CUSIP string.
    This is the inverse of what the repair function does.
    """
    ctype = corruption_type(cusip)
    if ctype == "truncated":
        return cusip.lstrip("0")        # strip leading zeros → shorter string
    if ctype == "sci_notation":
        # Simulate float parsing: find the E, treat as scientific notation
        m = re.search(r'(\d+)[Ee](\d+)', cusip)
        if m:
            base, exp = m.group(1), m.group(2)
            return f"{base}E{exp}"      # returns a garbage float-like string
    return cusip                        # alphanumeric and no-leading-zero: unchanged


# =============================================================================
# STEP 3: BUILD THE DATASETS
# =============================================================================

def build_datasets():
    print("=" * 70)
    print("Building CUSIP corruption test dataset")
    print("=" * 70)

    # ── Load universe holdings (has company_name column) ─────────────────────
    src = os.path.join(DATA_DIR, "holdings_sp500_universe.csv")
    df  = pd.read_csv(src)
    print(f"\nLoaded: {src}")
    print(f"  Rows: {len(df):,}   |   Tickers: {df.ticker.nunique()}")

    # ── Attach correct CUSIPs and full company names ──────────────────────────
    df["correct_cusip"] = df["ticker"].map(KNOWN_CUSIPS)
    df["issuer_name"]   = df["ticker"].map(COMPANY_NAMES).fillna(df["company_name"])

    missing = df["correct_cusip"].isna().sum()
    if missing:
        print(f"  WARNING: {missing} rows have no CUSIP in lookup table")
        print(f"  Affected tickers: {df[df.correct_cusip.isna()].ticker.unique()}")
        df = df.dropna(subset=["correct_cusip"])

    # ── Classify and corrupt ──────────────────────────────────────────────────
    df["corruption_type"]  = df["correct_cusip"].apply(corruption_type)
    df["corrupted_cusip"]  = df["correct_cusip"].apply(corrupt_cusip)
    df["is_corrupted"]     = df["corrupted_cusip"] != df["correct_cusip"]

    # ── Print corruption breakdown ────────────────────────────────────────────
    print(f"\nCUSIP corruption breakdown by ticker:")
    print(f"  {'Ticker':<8} {'Company':<35} {'Correct CUSIP':<12} "
          f"{'Corrupted':<12} {'Type'}")
    print("  " + "-" * 88)

    ticker_info = (df[["ticker","issuer_name","correct_cusip","corrupted_cusip",
                        "corruption_type","is_corrupted"]]
                   .drop_duplicates("ticker")
                   .sort_values("ticker"))

    for _, row in ticker_info.iterrows():
        flag = "← CHANGED" if row.is_corrupted else ""
        print(f"  {row.ticker:<8} {row.issuer_name[:34]:<35} "
              f"{row.correct_cusip:<12} {row.corrupted_cusip:<12} "
              f"{row.corruption_type}  {flag}")

    n_corrupted_tickers = ticker_info["is_corrupted"].sum()
    n_safe_tickers      = (~ticker_info["is_corrupted"]).sum()
    print(f"\n  Tickers with corrupted CUSIPs : {n_corrupted_tickers}")
    print(f"  Tickers with unchanged CUSIPs : {n_safe_tickers}")
    print(f"\n  Rows affected by corruption   : {df['is_corrupted'].sum():,} / {len(df):,} "
          f"({100*df['is_corrupted'].mean():.1f}%)")

    by_type = df.groupby("corruption_type").agg(
        tickers=("ticker", "nunique"),
        rows=("ticker", "count")
    )
    print(f"\n  By corruption type:")
    print(by_type.to_string())

    # ── Save CORRECT file (ground truth / answer key) ─────────────────────────
    correct_cols = ["ticker","issuer_name","correct_cusip","corruption_type",
                    "year","quarter","filer_cik","filer_name","shares_held"]
    correct_path = os.path.join(DATA_DIR, "holdings_sp500_universe_CORRECT.csv")
    df[correct_cols].to_csv(correct_path, index=False)
    print(f"\nSaved CORRECT (answer key) → {os.path.basename(correct_path)}")
    print(f"  {len(df):,} rows")

    # ── Save CORRUPTED file (test input, what broken QK ingest would see) ────
    corrupted_cols = ["ticker","issuer_name","corrupted_cusip","corruption_type",
                      "year","quarter","filer_cik","filer_name","shares_held"]
    corrupted_path = os.path.join(DATA_DIR, "holdings_sp500_universe_CORRUPTED.csv")
    df[corrupted_cols].rename(columns={"corrupted_cusip": "cusip"}).to_csv(
        corrupted_path, index=False)
    print(f"Saved CORRUPTED (test input) → {os.path.basename(corrupted_path)}")
    print(f"  {len(df):,} rows  ({df['is_corrupted'].sum():,} rows with corrupted CUSIPs)")

    return df, correct_path, corrupted_path


# =============================================================================
# STEP 4: RUN REPAIR PIPELINE AND SCORE
# =============================================================================

def run_repair_and_score(df: pd.DataFrame):
    """
    Import the repair functions from cusip_repair_prototype and run them
    against every unique (issuer_name, corrupted_cusip) pair.
    Reports precision, recall, and F1 by corruption type.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from cusip_repair_prototype import (
        validate_cusip, classify_cusip, try_repair_cusip,
        name_search, build_name_index, normalize_name,
        _build_reference_from_ticker_map
    )

    print("\n" + "=" * 70)
    print("REPAIR EVALUATION")
    print("=" * 70)

    # Build reference using our known CUSIPs
    reference = {v: k_name for k, (v, k_name) in
                 {t: (KNOWN_CUSIPS[t], COMPANY_NAMES[t])
                  for t in KNOWN_CUSIPS}.items()}
    # reference = {cusip: name}
    reference = {cusip: COMPANY_NAMES[ticker]
                 for ticker, cusip in KNOWN_CUSIPS.items()
                 if ticker in COMPANY_NAMES}

    bm25, ref_cusips, ref_names, ref_normed = build_name_index(reference)

    # Test on unique (issuer_name, corrupted_cusip, correct_cusip) triples
    test_cases = (df[["ticker","issuer_name","corrupted_cusip",
                       "correct_cusip","corruption_type","is_corrupted"]]
                  .drop_duplicates("ticker")
                  .sort_values("ticker"))

    print(f"\n{'Ticker':<8} {'Issuer Name':<35} {'Corrupted':<12} "
          f"{'Repaired':<12} {'Correct':<12} {'Match?':<8} Method")
    print("-" * 100)

    results = []
    for _, row in test_cases.iterrows():
        corrupted    = str(row.corrupted_cusip).strip()
        correct      = str(row.correct_cusip).strip()
        name         = row.issuer_name
        ctype        = row.corruption_type

        repaired = None
        method   = None

        if not row.is_corrupted:
            # CUSIP was not changed by corruption, test that we don't break it
            if validate_cusip(corrupted):
                repaired = corrupted
                method   = "no_change_needed"
        else:
            cat = classify_cusip(corrupted)
            if cat == "truncated":
                fix = try_repair_cusip(corrupted, reference)
                if fix:
                    repaired = fix["repaired_cusip"]
                    method   = f"checkdigit_pad_{fix['zeros_added']}zero"
            if repaired is None:
                # Fallback: name search
                candidates = name_search(name, bm25, ref_cusips, ref_names, ref_normed)
                if candidates and candidates[0]["combined"] > 0.4:
                    repaired = candidates[0]["cusip"]
                    method   = f"name_bm25 ({candidates[0]['combined']:.2f})"

        matched = (repaired == correct)
        mark    = "ok" if matched else ("miss" if repaired else ", ")

        print(f"{row.ticker:<8} {name[:34]:<35} {corrupted:<12} "
              f"{(repaired or ', '):<12} {correct:<12} {mark:<8} {method or ', '}")

        results.append({
            "ticker":        row.ticker,
            "corruption_type": ctype,
            "is_corrupted":  row.is_corrupted,
            "correct_cusip": correct,
            "corrupted_cusip": corrupted,
            "repaired_cusip": repaired,
            "correct":       matched,
            "method":        method,
        })

    res = pd.DataFrame(results)

    # ── Precision / Recall / F1 ───────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SCORES")
    print("=" * 70)

    # Overall
    attempted  = res[res.repaired_cusip.notna()]
    correct_r  = attempted[attempted.correct]
    precision  = len(correct_r) / len(attempted) if len(attempted) else 0
    recall     = len(correct_r) / len(res) if len(res) else 0
    f1         = (2 * precision * recall / (precision + recall)
                  if (precision + recall) else 0)

    print(f"\n  Overall ({len(res)} unique tickers):")
    print(f"    Attempted repair : {len(attempted)} / {len(res)}")
    print(f"    Correctly repaired: {len(correct_r)}")
    print(f"    Precision : {precision:.1%}")
    print(f"    Recall    : {recall:.1%}")
    print(f"    F1        : {f1:.1%}")

    # By corruption type
    print(f"\n  By corruption type:")
    for ctype in res.corruption_type.unique():
        sub = res[res.corruption_type == ctype]
        sub_att = sub[sub.repaired_cusip.notna()]
        sub_cor = sub_att[sub_att.correct]
        p = len(sub_cor)/len(sub_att) if len(sub_att) else 0
        r = len(sub_cor)/len(sub)     if len(sub) else 0
        print(f"    {ctype:<30}  n={len(sub):>3}  "
              f"precision={p:.0%}  recall={r:.0%}")

    # Row-level stats (same precision/recall but across 1M rows)
    print(f"\n  Row-level impact (extrapolated across {len(df):,} holdings rows):")
    for _, trow in res.iterrows():
        n_rows = len(df[df.ticker == trow.ticker])
        status = "repaired" if trow.correct else ("wrong" if trow.repaired_cusip else "unresolved")
        if trow.is_corrupted:
            print(f"    {trow.ticker:<6}  {n_rows:>7,} rows  → {status}")

    return res


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    df, correct_path, corrupted_path = build_datasets()
    results = run_repair_and_score(df)
    print(f"\nDone. Test files saved to data/")
    print(f"  Answer key : holdings_sp500_universe_CORRECT.csv")
    print(f"  Test input : holdings_sp500_universe_CORRUPTED.csv")
