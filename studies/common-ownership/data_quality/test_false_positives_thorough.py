"""
test_false_positives_thorough.py
=================================
Rigorous false positive analysis for the fuzzy name lookup.

THREE TEST SUITES:

1. STATE STREET 2015, the original 63 unpaddable CUSIPs
   Tests recall and FP rate on the real problem we're solving.

2. CROSS-COMPANY FP TEST, 74-ticker canonical reference
   For each ticker's canonical name, query the reference and verify the
   returned CUSIP matches the correct ticker. A wrong CUSIP = false positive.
   This is the most important FP test: does a correctly-typed company name
   retrieve itself and NOT retrieve a different company?

3. ADVERSARIAL CONFUSABLES, hand-crafted near-misses
   Company pairs that share bigrams but are different companies.
   Examples: "CDK GLOBAL" vs "RB GLOBAL", "FIRST ENERGY" vs "FIRST SOLAR",
   "US BANCORP" vs "US FOODS". Tests that first-token blocking + IDF prevents
   these from becoming false positives.

4. MIN_BIGRAMS COMPARISON, runs suite 1+2 with MIN_BIGRAMS=1 vs 2
   Shows what changes (good and bad) when we lower the gate.

HOW TO RUN
----------
  python3 scripts/test_false_positives_thorough.py
"""

import os, re, sys, importlib
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "..", "data")

AUDIT_PATH   = os.path.join(DATA_DIR, "audit_statestreet_2015_edgar_positions.csv")
REF74_PATH   = os.path.join(DATA_DIR, "cusip_reference_74tickers.csv")
FIVE_SRC_CSV = os.path.join(DATA_DIR, "five_source_reference.csv")
FIVE_SRC_IDX = os.path.join(DATA_DIR, "five_source_index.pkl")


# ── helpers ───────────────────────────────────────────────────────────────────

def cusip_check_digit(c8: str) -> str:
    total = 0
    for i, c in enumerate(c8.upper()):
        v = int(c) if c.isdigit() else (ord(c) - ord('A') + 10)
        if i % 2 == 1: v *= 2
        total += v // 10 + v % 10
    return str((10 - total % 10) % 10)

def classify_cusip(cusip_str: str):
    c = str(cusip_str).strip()
    # A 9-char CUSIP is already well-formed, not corrupted
    if len(c) >= 9:
        return 'valid', c
    # Short CUSIPs: check for scientific notation corruption (e.g. "876E110")
    # Only flag as sci_notation if the string is SHORT (< 9 chars) AND has E/e
    if re.search(r'[Ee]', c):
        return 'sci_notation', None
    for n in range(1, 4):
        candidate = '0' * n + c
        if len(candidate) == 9:
            if cusip_check_digit(candidate[:8]) == candidate[8]:
                return 'padded', candidate
    return 'unresolvable', None

def load_state_street_failures():
    audit = pd.read_csv(AUDIT_PATH)
    audit['cusip_str'] = audit['cusip'].astype(str).str.strip()
    failures = []
    for _, row in audit.iterrows():
        method, _ = classify_cusip(row['cusip_str'])
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


# ── Suite 1: State Street 2015 ─────────────────────────────────────────────

def suite_statestreet(lookup_fn, index, label=""):
    """
    Run the 63-row State Street test.
    Uses preprocess() on both sides of evaluate_match() for fair token overlap.
    """
    import fuzzy_name_lookup as fnl

    failures = load_state_street_failures()
    results = []

    for _, row in failures.iterrows():
        detail = lookup_fn(
            raw_name     = row['name'],
            filing_date  = row['filing_date'],
            index        = index,
            threshold    = 0.30,
            return_details=True
        )

        if detail:
            # preprocess both sides before token overlap
            orig_prep  = fnl.preprocess(row['name'])
            match_prep = fnl.preprocess(detail['name'])
            STOP = {"inc","corp","co","ltd","the","new","com","cos","grp","group","llc","plc"}
            def toks(s):
                return set(s.split()) - STOP
            orig_toks  = toks(orig_prep)
            match_toks = toks(match_prep)
            overlap    = len(orig_toks & match_toks)
            if overlap >= 2:
                verdict = "CORRECT"
            elif overlap == 1 and len(orig_toks) <= 2:
                verdict = "LIKELY"
            else:
                verdict = "WRONG"
            results.append({
                'original_name':  row['name'],        # keep original separate
                'original_cusip': row['original_cusip'],
                'method':         row['method'],
                'quarter':        row['quarter'],
                'filing_date':    row['filing_date'],
                'matched_name':   detail['name'],
                'matched_id':     detail['identifier'],
                'score':          detail['score'],
                'entity_type':    detail.get('entity_type',''),
                'confidence':     detail.get('confidence',''),
                'verdict':        verdict,
            })
        else:
            results.append({
                'original_name':  row['name'],
                'original_cusip': row['original_cusip'],
                'method':         row['method'],
                'quarter':        row['quarter'],
                'filing_date':    row['filing_date'],
                'matched_name':   None,
                'matched_id':     None,
                'score':          0.0,
                'entity_type':    None,
                'confidence':     None,
                'verdict':        'NULL',
            })

    df = pd.DataFrame(results)
    correct = (df['verdict'] == 'CORRECT').sum()
    likely  = (df['verdict'] == 'LIKELY').sum()
    wrong   = (df['verdict'] == 'WRONG').sum()
    null    = (df['verdict'] == 'NULL').sum()
    total   = len(df)

    print(f"\n{'─'*55}")
    print(f"SUITE 1: STATE STREET 2015  {label}")
    print(f"{'─'*55}")
    print(f"  CORRECT:   {correct:>3}  ({correct/total*100:.1f}%)")
    print(f"  LIKELY:    {likely:>3}  ({likely/total*100:.1f}%)")
    print(f"  WRONG (FP):{wrong:>3}  ({wrong/total*100:.1f}%)")
    print(f"  NULL:      {null:>3}  ({null/total*100:.1f}%)")
    print(f"  Recall:    {correct+likely}/{total} = {(correct+likely)/total*100:.1f}%")
    print(f"  FP rate:   {wrong}/{total} = {wrong/total*100:.1f}%")

    if wrong > 0:
        print(f"\n  False positives:")
        for _, r in df[df['verdict']=='WRONG'].iterrows():
            print(f"    [{r['score']:.2f}] \"{r['original_name']}\"")
            print(f"           → \"{r['matched_name']}\"  ← WRONG")

    null_df = df[df['verdict']=='NULL']
    if len(null_df):
        print(f"\n  NULLs:")
        for _, r in null_df.iterrows():
            print(f"    \"{r['original_name']}\"")

    return df


# ── Suite 2: Cross-company FP test (74 tickers) ──────────────────────────────

def suite_cross_company(lookup_fn, index, label=""):
    """
    Query each of the 74 canonical ticker names and verify:
      CORRECT: returned CUSIP matches the known correct CUSIP
      FP : returned CUSIP is a different company
      NULL: no match found (miss, not a FP)
    """
    ref74 = pd.read_csv(REF74_PATH)
    results = []

    for _, row in ref74.iterrows():
        correct_cusip = str(row['cusip']).strip()

        # Query with both canonical name and SEC 13F name (abbreviation)
        for name_col in ['canonical_name', 'sec13f_name']:
            qname = str(row.get(name_col, '')).strip()
            if not qname or qname == 'nan':
                continue

            detail = lookup_fn(
                raw_name      = qname,
                filing_date   = '2015-06-30',
                index         = index,
                threshold     = 0.30,
                return_details= True
            )

            if detail:
                returned_cusip = str(detail['identifier']).strip()
                verdict = 'CORRECT' if returned_cusip == correct_cusip else 'FP'
            else:
                returned_cusip = None
                verdict = 'NULL'

            results.append({
                'ticker':         row['ticker'],
                'query_name':     qname,
                'name_type':      name_col,
                'correct_cusip':  correct_cusip,
                'returned_cusip': returned_cusip,
                'score':          detail['score'] if detail else 0.0,
                'confidence':     detail.get('confidence') if detail else None,
                'matched_name':   detail.get('name') if detail else None,
                'verdict':        verdict,
            })

    df = pd.DataFrame(results)
    correct = (df['verdict'] == 'CORRECT').sum()
    fp      = (df['verdict'] == 'FP').sum()
    null    = (df['verdict'] == 'NULL').sum()
    total   = len(df)

    print(f"\n{'─'*55}")
    print(f"SUITE 2: CROSS-COMPANY (74 tickers × 2 name forms)  {label}")
    print(f"{'─'*55}")
    print(f"  CORRECT:   {correct:>3}  ({correct/total*100:.1f}%)")
    print(f"  FP:        {fp:>3}  ({fp/total*100:.1f}%)")
    print(f"  NULL:      {null:>3}  ({null/total*100:.1f}%)")
    print(f"  Precision: {correct/(correct+fp)*100:.1f}%  (of resolved, how many are right)")

    if fp > 0:
        print(f"\n  FALSE POSITIVES (returned wrong company):")
        for _, r in df[df['verdict']=='FP'].iterrows():
            print(f"    [{r['score']:.2f}] [{r['name_type']}] \"{r['query_name']}\"")
            print(f"           → \"{r['matched_name']}\"  (CUSIP {r['returned_cusip']})")
            print(f"           CORRECT CUSIP: {r['correct_cusip']}")

    return df


# ── Suite 3: Adversarial confusables ──────────────────────────────────────────

CONFUSABLES = [
    # (query_name, what_it_should_NOT_match, filing_date, description)
    # Pairs where the wrong match is a real company in the reference

    # "GLOBAL" suffix trap, many companies end in Global
    ("CDK GLOBAL INC",          "RB GLOBAL",        "2015-06-30", "CDK vs RB, shares 'global'"),
    ("RB GLOBAL INC",           "CDK GLOBAL",        "2015-06-30", "RB vs CDK, shares 'global'"),
    ("US FOODS HOLDING CORP",   "US BANCORP",        "2015-06-30", "US Foods vs US Bancorp"),
    ("FIRST SOLAR INC",         "FIRST ENERGY CORP", "2015-06-30", "First Solar vs First Energy"),
    ("AMERICAN EXPRESS CO",     "AMERICAN AIRLINES", "2015-06-30", "AmEx vs American Airlines"),
    ("AMERICAN AIRLINES GROUP", "AMERICAN EXPRESS",  "2015-06-30", "American Airlines vs AmEx"),
    ("INTEL CORP",              "INTEL CAP CORP",    "2015-06-30", "Intel Corp vs Intel Cap Corp"),
    ("GENERAL MOTORS CO",       "GENERAL MILLS INC", "2015-06-30", "GM vs General Mills"),
    ("GENERAL MILLS INC",       "GENERAL MOTORS CO", "2015-06-30", "General Mills vs GM"),
    ("GOLDMAN SACHS GROUP INC", "GOLDMAN SACHS ETF", "2015-06-30", "Goldman equity vs Goldman ETF"),
    ("WELLS FARGO",             "WELLS FARGO BANK",  "2015-06-30", "Wells Fargo parent vs bank sub"),
    ("JP MORGAN CHASE",         "JP MORGAN FUNDS",   "2015-06-30", "JPM equity vs JPM fund"),
    ("APPLE INC",               "APPLE HOSPITALITY", "2015-06-30", "Apple tech vs Apple REIT"),
    ("MICROSOFT CORP",          "MICROCHIP TECH",    "2015-06-30", "Microsoft vs Microchip"),
    ("VISA INC",                "VIASAT INC",        "2015-06-30", "Visa vs ViaSat"),
    # Short name trap, should not match the wrong company
    ("NCR CORP",                "NCR ATLEOS CORP",   "2015-06-30", "NCR Corp vs NCR Atleos"),
    ("HCI GROUP INC",           "HCI BANCORP",       "2015-06-30", "HCI Group vs HCI Bancorp"),
]

def suite_adversarial(lookup_fn, index, label=""):
    """
    For each confusable pair, verify the query does NOT return the wrong company.
    A match is only wrong if it returns a name more similar to the confusable
    than to the actual query company.
    """
    import fuzzy_name_lookup as fnl

    print(f"\n{'─'*55}")
    print(f"SUITE 3: ADVERSARIAL CONFUSABLES  {label}")
    print(f"{'─'*55}")

    false_positives = 0
    total = len(CONFUSABLES)

    for query_name, should_not_match, fdate, desc in CONFUSABLES:
        detail = lookup_fn(
            raw_name      = query_name,
            filing_date   = fdate,
            index         = index,
            threshold     = 0.30,
            return_details= True
        )

        if detail:
            matched = detail['name']
            # Check if returned name is more similar to the "wrong" company
            # than to the query company
            m_prep = fnl.preprocess(matched)
            q_prep = fnl.preprocess(query_name)
            w_prep = fnl.preprocess(should_not_match)

            q_bigs = fnl.make_bigrams(q_prep)
            w_bigs = fnl.make_bigrams(w_prep)
            m_bigs = fnl.make_bigrams(m_prep)

            sim_to_query = fnl.bigram_jaccard(q_bigs, m_bigs)
            sim_to_wrong = fnl.bigram_jaccard(w_bigs, m_bigs)

            if sim_to_wrong > sim_to_query and sim_to_wrong > 0.5:
                status = "FP"
                false_positives += 1
                print(f"  FP  [{detail['score']:.2f}] \"{query_name}\"")
                print(f"         → \"{matched}\"  (should NOT match \"{should_not_match}\")")
                print(f"         Desc: {desc}")
            else:
                status = "OK"
                print(f"  OK  [{detail['score']:.2f}] \"{query_name}\" → \"{matched}\"")
        else:
            print(f"  OK  [NULL] \"{query_name}\" → no match (safe)")

    print(f"\n  Adversarial FP: {false_positives}/{total} = {false_positives/total*100:.1f}%")
    return false_positives, total


# ── Suite 3b: Large-scale negative test ──────────────────────────────────────

def suite_large_negative(lookup_fn, index, label=""):
    """
    Take ~200 company names from the SEC 13F official list that are
    OUTSIDE our 74-ticker universe. For each, run the lookup and check:
      - A NULL return is correct (company not in our target universe)
      - A return is a FP only if it maps to one of the 74 canonical CUSIPs

    This tests: does the algorithm fabricate matches for random companies?
    The 74 canonical CUSIPs are what we care about not cross-contaminating.
    """
    import fuzzy_name_lookup as fnl

    # Load the 74-ticker CUSIPs we care about
    ref74 = pd.read_csv(REF74_PATH)
    target_cusips = set(ref74['cusip'].astype(str).str.strip().tolist())

    # Load SEC 13F official list, these are real securities we did NOT
    # include in our 74-ticker universe. Querying them should NOT return
    # any of our 74 canonical CUSIPs.
    sec13f = pd.read_csv(os.path.join(DATA_DIR, "sec_13f_official_list.csv"))

    # Filter to primary equities only, exclude our 74 tickers by CUSIP
    primary = sec13f[sec13f.get("is_primary", pd.Series([True]*len(sec13f))) != False]
    outside = primary[~primary["cusip"].astype(str).str.strip().isin(target_cusips)]

    # Sample 300 random names
    import random
    random.seed(42)
    sample = outside.sample(min(300, len(outside)), random_state=42)

    print(f"\n{'─'*55}")
    print(f"SUITE 3b: LARGE-SCALE NEGATIVE TEST ({len(sample)} random companies)  {label}")
    print(f"{'─'*55}")

    fp_count = 0
    resolved_count = 0
    fp_examples = []

    for _, row in sample.iterrows():
        qname = str(row.get("company_name", row.get("name", ""))).strip()
        if not qname:
            continue

        detail = lookup_fn(
            raw_name      = qname,
            filing_date   = "2015-06-30",
            index         = index,
            threshold     = 0.30,
            return_details= True
        )

        if detail:
            resolved_count += 1
            returned_cusip = str(detail['identifier']).strip()
            if returned_cusip in target_cusips:
                fp_count += 1
                fp_examples.append((qname, detail['name'], detail['score'], returned_cusip))

    null_count = len(sample) - resolved_count

    print(f"  Queries:  {len(sample)}")
    print(f"  Resolved: {resolved_count}  (found SOMETHING in reference)")
    print(f"  NULLs:    {null_count}  (no match, expected for companies not in our universe)")
    print(f"  FP (wrong 74-ticker CUSIP returned): {fp_count}  ({fp_count/len(sample)*100:.2f}%)")

    if fp_examples:
        print(f"\n  Cases where a 74-ticker CUSIP was wrongly returned:")
        for q, m, s, c in fp_examples:
            ticker = ref74[ref74['cusip']==c]['ticker'].values[0] if c in target_cusips else '???'
            print(f"    [{s:.2f}] \"{q}\"")
            print(f"           → \"{m}\"  (CUSIP={c}, ticker={ticker})  ← WRONG")
    else:
        print(f"\n  Zero contamination: no random company was mapped to any of the 74 target CUSIPs.")

    return fp_count, len(sample)


# ── Suite 4: MIN_BIGRAMS comparison ───────────────────────────────────────────

def suite_min_bigrams_comparison():
    """
    Compare MIN_BIGRAMS=2 (current) vs MIN_BIGRAMS=1.
    Rebuilds the index for each setting.
    Runs Suite 1 + Suite 2 under each.
    """
    import fuzzy_name_lookup as fnl

    print(f"\n{'='*55}")
    print("SUITE 4: MIN_BIGRAMS COMPARISON (2 vs 1)")
    print(f"{'='*55}")

    results_by_setting = {}

    for min_bg in [2, 1]:
        print(f"\n{'─'*55}")
        print(f"Setting MIN_BIGRAMS = {min_bg}")
        print(f"{'─'*55}")

        # Patch the module-level constant
        fnl.MIN_BIGRAMS = min_bg

        # Rebuild index from five-source reference with this setting
        print("  Building index...")
        index = fnl.build_index(FIVE_SRC_CSV)
        n_entries = len(index['entries'])
        n_bigrams = len(index['inverted'])
        print(f"  Index: {n_entries:,} entries, {n_bigrams:,} unique bigrams")

        # Run State Street suite (just counts, no verbose per-row output)
        failures = load_state_street_failures()
        ss_correct = ss_wrong = ss_null = 0
        wrong_examples = []

        STOP = {"inc","corp","co","ltd","the","new","com","cos","grp","group","llc","plc"}
        def toks(s): return set(s.split()) - STOP

        for _, row in failures.iterrows():
            detail = fnl.lookup(
                raw_name      = row['name'],
                filing_date   = row['filing_date'],
                index         = index,
                threshold     = 0.30,
                return_details= True
            )
            if detail:
                orig_prep  = fnl.preprocess(row['name'])
                match_prep = fnl.preprocess(detail['name'])
                overlap = len(toks(orig_prep) & toks(match_prep))
                if overlap >= 2:
                    ss_correct += 1
                elif overlap == 1 and len(toks(orig_prep)) <= 2:
                    ss_correct += 1
                else:
                    ss_wrong += 1
                    wrong_examples.append((row['name'], detail['name'], detail['score']))
            else:
                ss_null += 1

        total_ss = len(failures)
        print(f"  [SS2015] Recall: {ss_correct}/{total_ss} = {ss_correct/total_ss*100:.1f}%  |  FP: {ss_wrong}  |  NULL: {ss_null}")
        if wrong_examples:
            print(f"  [SS2015] New FPs with MIN_BIGRAMS={min_bg}:")
            for q, m, s in wrong_examples:
                print(f"    [{s:.2f}] \"{q}\" → \"{m}\"")

        # Run cross-company suite
        ref74 = pd.read_csv(REF74_PATH)
        xc_correct = xc_fp = xc_null = 0
        fp_examples = []

        for _, row in ref74.iterrows():
            correct_cusip = str(row['cusip']).strip()
            for name_col in ['canonical_name', 'sec13f_name']:
                qname = str(row.get(name_col, '')).strip()
                if not qname or qname == 'nan':
                    continue
                detail = fnl.lookup(qname, '2015-06-30', index, threshold=0.30, return_details=True)
                if detail:
                    if str(detail['identifier']).strip() == correct_cusip:
                        xc_correct += 1
                    else:
                        xc_fp += 1
                        fp_examples.append((row['ticker'], name_col, qname, detail['name'], detail['score']))
                else:
                    xc_null += 1

        total_xc = len(ref74) * 2
        resolved_xc = xc_correct + xc_fp
        precision_xc = xc_correct / resolved_xc * 100 if resolved_xc > 0 else 0
        print(f"  [XC74]   Correct: {xc_correct}/{total_xc} | FP: {xc_fp} | NULL: {xc_null} | Precision: {precision_xc:.1f}%")
        if fp_examples:
            print(f"  [XC74]   FPs with MIN_BIGRAMS={min_bg}:")
            for ticker, nc, q, m, s in fp_examples[:10]:
                print(f"    [{s:.2f}] {ticker} [{nc}] \"{q}\" → \"{m}\"")

        results_by_setting[min_bg] = {
            'ss_correct': ss_correct, 'ss_wrong': ss_wrong, 'ss_null': ss_null,
            'xc_correct': xc_correct, 'xc_fp': xc_fp, 'xc_null': xc_null,
        }

    # Summary comparison
    print(f"\n{'─'*55}")
    print("COMPARISON SUMMARY")
    print(f"{'─'*55}")
    print(f"{'Metric':<30} {'MIN_BG=2':>10} {'MIN_BG=1':>10}")
    r2, r1 = results_by_setting[2], results_by_setting[1]
    print(f"{'SS2015 recall':<30} {r2['ss_correct']}/63{' ':>5} {r1['ss_correct']}/63")
    print(f"{'SS2015 false positives':<30} {r2['ss_wrong']:>10} {r1['ss_wrong']:>10}")
    print(f"{'SS2015 NULLs':<30} {r2['ss_null']:>10} {r1['ss_null']:>10}")
    print(f"{'XC74 correct':<30} {r2['xc_correct']}/148{' ':>4} {r1['xc_correct']}/148")
    print(f"{'XC74 false positives':<30} {r2['xc_fp']:>10} {r1['xc_fp']:>10}")

    return results_by_setting


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    import fuzzy_name_lookup as fnl

    print("=" * 55)
    print("THOROUGH FALSE POSITIVE ANALYSIS")
    print("=" * 55)

    # Load the five-source index (or build if missing)
    if os.path.exists(FIVE_SRC_IDX):
        print(f"\nLoading cached five-source index...")
        index = fnl.load_index(FIVE_SRC_IDX)
        n_entries = len(index['entries'])
        n_bigrams = len(index['inverted'])
        print(f"Index: {n_entries:,} entries, {n_bigrams:,} unique bigrams")
    else:
        print("\nBuilding five-source index...")
        index = fnl.build_index(FIVE_SRC_CSV, save_path=FIVE_SRC_IDX)

    # Suite 1: State Street 2015 (current MIN_BIGRAMS=2)
    suite_statestreet(fnl.lookup, index, label="[fixed equity filter, MIN_BIGRAMS=2]")

    # Suite 2: Cross-company FP (current MIN_BIGRAMS=2)
    xc_df = suite_cross_company(fnl.lookup, index, label="[fixed equity filter, MIN_BIGRAMS=2]")

    # Categorize XC FPs: same-company-different-CUSIP vs genuinely different company
    if len(xc_df[xc_df['verdict']=='FP']) > 0:
        ref = pd.read_csv(FIVE_SRC_CSV)
        print(f"\n  XC FP CATEGORISATION (same-company CUSIP mismatch vs different company):")
        for _, r in xc_df[xc_df['verdict']=='FP'].iterrows():
            rc = str(r['returned_cusip'])
            cc = str(r['correct_cusip'])
            same_co = rc[:6] == cc[:6]
            returned_rows = ref[ref['cusip']==rc]
            ret_type = returned_rows['entity_type'].iloc[0] if len(returned_rows) else '???'
            label_str = 'SAME-CO diff-instrument' if same_co else '*** DIFF COMPANY ***'
            print(f"    [{r['score']:.2f}] {r['ticker']} \"{r['query_name'][:28]}\" "
                  f"→ \"{str(r['matched_name'])[:28]}\" [{ret_type}]  {label_str}")

    # Suite 3: Adversarial confusables
    suite_adversarial(fnl.lookup, index, label="[fixed equity filter, MIN_BIGRAMS=2]")

    # Suite 3b: Large-scale negative test
    suite_large_negative(fnl.lookup, index, label="[fixed equity filter, MIN_BIGRAMS=2]")

    # Suite 4: MIN_BIGRAMS=1 vs 2 comparison
    suite_min_bigrams_comparison()

    print(f"\n{'='*55}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
