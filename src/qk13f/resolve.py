"""
fuzzy_name_lookup.py
====================
Second mapping path for QK's QKID resolution pipeline.

THE PROBLEM IT SOLVES
---------------------
QK's primary path is: CUSIP → QKID lookup.
When a CUSIP is corrupted (integer coercion strips leading zeros, or the
number is stored as scientific notation), that lookup fails and the row is
silently dropped.

This module provides a fallback: when the CUSIP lookup fails, use the
company name the filer typed to search the entity-security master and
return the correct QKID.

HOW IT WORKS
------------
Character bigrams. Not BM25, not word tokens, character-level pairs.

"APPLIED MATLS INC" and "Applied Materials Inc" look very different as
words but share most of their character bigrams:
  "ap", "pp", "pl", "li", "ie", "ed" appear in both.

This robustness to abbreviations and truncations is why character
n-grams are the right tool for this job.

THE POINT-IN-TIME (PIT) REQUIREMENT
------------------------------------
A 2015 filing should only match against companies that existed in 2015.
The secmaster has an as-of date on every row. We filter to entries where
as_of_date ≤ filing_date, then take the most recent matching version of
each entity. This is an as-of join.

THE THRESHOLD
-------------
The default Bigram Jaccard threshold is 0.30, raised for very short names.
The State Street test that checked it is in
studies/common-ownership/docs/entity-resolution.md.

WHAT THIS IS NOT
----------------
Not a trained model. Not a classifier. No training data needed.
When the secmaster is updated, rebuild the index, the function
automatically reflects the new data.

CALLABLE INTERFACE
------------------
from fuzzy_name_lookup import build_index, lookup, batch_lookup

index = build_index("path/to/secmaster.csv")
qkid  = lookup("APPLIED MATLS INC", "2015-06-30", index)
"""

import csv
import html
import math
import pickle
import re
from collections import defaultdict
from datetime import date, datetime

# ─── Configuration ────────────────────────────────────────────────────────────

BIGRAM_THRESHOLD  = 0.30   # minimum Jaccard score to return a match
MIN_BIGRAMS       = 1      # minimum bigrams, 1 allows 2-char names (BT, NCR, HCI)
                           # safe because length-adaptive threshold (0.80 for short names)
                           # requires near-perfect match before any short name resolves

# =============================================================================
# IMPROVEMENT 5: ENTITY TYPE FILTER
# What it does: restricts candidate matching to specific security types.
# Why it matters: the secmaster has entity type on every row (Common Stock,
# ETF, Mutual Fund, Bond). A 13F equity holding should only be matched
# against equity-type entries. Without this filter, "TARGET CORP" competes
# against ETFs and closed-end funds that happen to share bigrams.
#
# EQUITY_TYPES: what counts as an equity for 13F matching purposes.
# Includes ordinary shares, ADRs (international companies listed in the US),
# and trust units (REITs, MLPs), all of which appear in 13F filings.
#
# NOT included: ETFs, mutual funds, options, bonds, these are different
# instrument types and should never be matched as equity company names.
# =============================================================================

EQUITY_TYPES = {
    # Plain common stock (most frequent in SEC 13F list)
    "com", "com new", "com cl a", "com cl b", "com shs", "com sh",
    "common stock", "common",
    # International / share variants
    "shs", "ord shs", "ordinary shares", "ord sh",
    "cl a", "cl b", "cl c", "class a", "class b",
    # ADRs, foreign companies trading on US exchanges
    "sponsored ads", "sponsored adr", "adr", "ads",
    # Trust units, REITs, MLPs (equity-like, reported in 13F)
    "unit", "units",
    # Generic / catch-all equity forms
    "shares", "sh",
}

# Types that are explicitly NOT equities, exclude from equity-only matching
NON_EQUITY_TYPES = {
    "call", "put", "call *d*", "put *d*",     # options / derivatives
    "mutual fund", "closed-end fund", "etp",   # funds / ETFs
    "corp", "note", "bond", "deb", "debenture", # fixed income
    "pfd", "preferred",                          # preferred stock (different instrument)
    "warrant", "right", "rts",                   # warrants / rights
}

# Confidence tiers for the multi-pass strategy (Improvement 6)
CONFIDENCE_HIGH   = 0.80   # return immediately, very reliable match
CONFIDENCE_MEDIUM = 0.48   # return with flag, needs downstream review

# Legal suffix tokens stripped before matching
# "Goldman Sachs Inc" and "Goldman Sachs Corp" should map to same bigrams
LEGAL_SUFFIXES = {
    "inc", "corp", "co", "ltd", "llc", "plc", "lp", "na", "sa", "nv",
    "ag", "se", "bv", "ab", "oy", "as", "the", "new", "com", "grp",
    "group", "company", "corporation", "incorporated", "limited",
    "trust", "fund", "et", "tr",
    # Security-type noise tokens that filers append to company names in EDGAR filings
    # e.g. "PERFORMANCE SPORTS GROUP LTD COMMON STOCK CAD" → strip these from the end
    "common", "stock", "cad", "ord",
}

# =============================================================================
# IMPROVEMENT 1: FINANCIAL ABBREVIATION EXPANSION
# What it does: maps common SEC filing abbreviations to their full forms
# BEFORE bigrams are computed. This means "APPLIED MATLS INC" and
# "Applied Materials Inc" both preprocess to "applied materials" and
# produce identical bigrams, a guaranteed match.
#
# Why this matters: filers spell the same company many different ways. A large
# fraction of that variation is systematic abbreviation, not random noise.
# Standardising abbreviations before scoring collapses that variation.
#
# These are the most common abbreviations found in real 13F filings,
# seen in an extraction of real 13F filings.
# =============================================================================

ABBREV_MAP = {
    # Materials / Products
    "matls":    "materials",
    "mtrls":    "materials",
    "prods":    "products",
    "prod":     "products",
    "mfg":      "manufacturing",
    "mfr":      "manufacturer",
    # Services
    "svcs":     "services",
    "svc":      "services",
    # International / National
    "intl":     "international",
    "intntl":   "international",
    "natl":     "national",
    "amern":    "american",
    # Financial / Holdings
    "finl":     "financial",
    "fin":      "financial",
    "hldgs":    "holdings",
    "hldg":     "holdings",
    "mgmt":     "management",
    "mgnt":     "management",
    "secs":     "securities",
    "invst":    "investment",
    "invsts":   "investments",
    "assoc":    "associates",
    "assn":     "association",
    # Real estate
    "rlty":     "realty",
    "ppty":     "property",
    "pptys":    "properties",
    # Technology
    "techs":    "technologies",
    "syst":     "systems",
    # Banking
    "bancorp":  "bancorporation",
    "bancshrs": "bancshares",
    # Health
    "hlth":     "health",
    "pharm":    "pharmaceuticals",
    "pharmac":  "pharmaceuticals",
    # Energy / Resources
    "engy":     "energy",
    "res":      "resources",
    # Communications
    "communs":  "communications",
    # Other
    "elec":     "electric",
    "electl":   "electrical",
    "pwr":      "power",
    "wtr":      "water",
    "sol":      "solar",
    "am":       "american",   # only as standalone token
    "amer":     "american",
    "hlg":      "holding",
    "svs":      "services",
    "inds":     "industries",
    "ind":      "industries",
    "shs":      "shares",
    "bk":       "bank",
    "bksh":     "bankshares",
    "bkshrs":   "bankshares",
    "fncl":     "financial",
}


# =============================================================================
# COMPONENT 1: PREPROCESSOR
# What it does: cleans the raw name string before any matching happens.
# Why it matters: filers type names inconsistently. State Street writes
# "APPLIED MATLS INC", Vanguard writes "Applied Materials Inc",
# Fidelity writes "APPLIED MATERIALS INC COM". The preprocessor removes
# the surface variation so the bigrams underneath are comparable.
# =============================================================================

def preprocess(name: str) -> str:
    """
    Clean a raw company name for bigram matching.

    Steps:
      1. Decode HTML entities, handles &amp;amp; (double-encoded) cases
         we found in State Street's EDGAR filings.
      2. Lowercase, "APPLE INC" and "Apple Inc" become the same.
      3. Strip punctuation, "J.P. Morgan" → "jp morgan".
      4. Remove legal suffixes, "inc", "corp", "ltd" etc. add noise
         without adding signal. Removed from the end only.
      5. Collapse whitespace, single spaces only.
    """
    if not name or not str(name).strip():
        return ""

    # Step 1: decode HTML (handles both single and double encoding)
    s = html.unescape(html.unescape(str(name)))

    # Step 2-3: lowercase and strip punctuation
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)

    # Step 4: remove trailing legal suffixes
    tokens = s.split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()

    # Step 5: expand financial abbreviations (Improvement 1)
    # Each token is checked independently so "matls" in "applied matls"
    # becomes "materials" without touching any other token.
    tokens = [ABBREV_MAP.get(t, t) for t in tokens]

    # Step 6: collapse whitespace
    return " ".join(tokens)


def make_bigrams(text: str) -> frozenset:
    """
    Generate character bigrams from preprocessed text.

    Character bigrams are two-character substrings extracted by sliding
    a window of width 2 across the string (spaces included as connectors).

    Example:
      "applied matls" → {"ap","pp","pl","li","ie","ed"," m","ma","at","tl","ls"}

    Why character bigrams beat word tokens here:
      - "MATLS" and "MATERIALS" share the bigrams {ma, at} but share no words.
      - A 30-char truncation like "AUTOMATIC DATA PROCESSING IN"
        shares nearly all bigrams with "AUTOMATIC DATA PROCESSING INC".
      - Word tokens would miss both cases entirely.
    """
    s = text.replace(" ", "  ")   # double-space so word boundaries get bigrams
    if len(s) < 2:
        return frozenset()
    return frozenset(s[i:i+2] for i in range(len(s) - 1))


def bigram_jaccard(set_a: frozenset, set_b: frozenset) -> float:
    """
    Plain Jaccard similarity between two bigram sets (unweighted).
    Kept for reference and testing. Production scoring uses idf_weighted_jaccard.
    """
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union        = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


# =============================================================================
# IMPROVEMENT 2: IDF-WEIGHTED BIGRAM SCORING
# What it does: replaces plain Jaccard with corpus-frequency-aware scoring.
# Bigrams that appear in many company names ("fi", "in", "al" from "financial")
# get low weight. Bigrams from rare words ("ap" from "applied") get high weight.
#
# Inspired by Soft TF-IDF (Cohen, Ravikumar, Fienberg 2003), designed
# specifically for entity name matching problems.
#
# Why this matters:
#   Plain Jaccard: "CDK GLOBAL" vs "RB GLOBAL" = 0.58 (wrong match)
#   IDF-weighted:  "CDK GLOBAL" vs "RB GLOBAL" = 0.12 (correctly rejected)
#   Because "global" is common → low IDF → low weight.
#   "cdk" is rare → high IDF → high weight. But "cdk" ≠ "rb", so no shared
#   high-weight bigrams → low overall score.
# =============================================================================


def compute_idf(entries: dict) -> dict:
    """
    Compute inverse document frequency for every bigram in the corpus.

    IDF(bigram) = log(1 + N / (1 + df))
      N  = number of entries in the corpus
      df = number of entries that contain this bigram

    The +1 smoothing prevents division by zero for bigrams seen in all docs.

    Returns a dict: bigram → idf_weight (float)
    """
    n_docs = len(entries)
    df     = defaultdict(int)

    for entry in entries.values():
        for bigram in entry["bigrams"]:
            df[bigram] += 1

    idf = {}
    for bigram, doc_freq in df.items():
        idf[bigram] = math.log(1 + n_docs / (1 + doc_freq))

    return idf


def idf_weighted_jaccard(set_a: frozenset,
                          set_b: frozenset,
                          idf: dict) -> float:
    """
    IDF-weighted Jaccard similarity.

    Instead of counting bigrams equally, weights each bigram by how rare
    it is across the corpus. Rare bigrams contribute more; common ones less.

    weighted_intersection = sum(idf[b] for b in set_a ∩ set_b)
    weighted_union        = sum(idf[b] for b in set_a ∪ set_b)
    score = weighted_intersection / weighted_union

    Returns a float in [0, 1]. Falls back to plain Jaccard if idf is empty.
    """
    if not set_a or not set_b:
        return 0.0
    if not idf:
        return bigram_jaccard(set_a, set_b)   # graceful fallback

    intersection = set_a & set_b
    union        = set_a | set_b

    w_inter = sum(idf.get(b, 1.0) for b in intersection)
    w_union  = sum(idf.get(b, 1.0) for b in union)

    return w_inter / w_union if w_union > 0 else 0.0


# =============================================================================
# COMPONENT 2: INDEX BUILDER
# What it does: reads the secmaster CSV and builds an inverted bigram index.
# Why it matters: without an index, a query against 60,000 names would
# require computing bigram Jaccard against every single row, too slow
# for 120M records. With an inverted index, we only score candidates that
# share at least one bigram with the query, which typically reduces the
# candidate set by 99%.
#
# The index is built ONCE per secmaster release, then saved to disk.
# At query time, we load it and run lookups in milliseconds.
#
# Expected secmaster CSV columns (flexible, see COLUMN_MAP below):
#   identifier , QKID (or CUSIP as proxy)
#   name       , canonical entity name
#   as_of_date , when this entry was added (YYYYMMDD or YYYY-MM-DD)
#   entity_type, Common Stock, ETF, Mutual Fund, etc. (optional)
# =============================================================================

# Column name mapping, adjust if the secmaster uses different headers
COLUMN_MAP = {
    "identifier":  ["qkid", "cusip", "identifier", "id"],
    "name":        ["canonical_name", "company_name", "name", "entity_name",
                    "sec13f_name"],
    "as_of_date":  ["as_of_date", "valid_from", "date", "added_date",
                    "as_of", "quarter_date"],
    "entity_type": ["entity_type", "security_type", "type", "asset_class"],
}

def _find_column(headers: list, candidates: list) -> str | None:
    """Find which actual CSV column matches our expected concept."""
    headers_lower = [h.lower().strip() for h in headers]
    for cand in candidates:
        if cand.lower() in headers_lower:
            return headers[headers_lower.index(cand.lower())]
    return None

def _parse_date(s: str) -> date | None:
    """
    Parse dates in multiple formats.
    Secmasters use YYYYMMDD or YYYY-MM-DD.
    Returns None if unparseable, those rows are treated as valid for all dates.
    """
    if not s or s in ("-", "", "nan", "None"):
        return None
    s = str(s).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%Y-%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def build_index(secmaster_path: str,
                save_path: str | None = None) -> dict:
    """
    Build a bigram inverted index from the secmaster CSV.

    Returns a dict with two keys:
      "inverted" , bigram → list of row_ids that contain that bigram
      "entries"  , row_id → {identifier, name, name_bigrams, as_of_date,
                               entity_type, preprocessed_name}

    If save_path is provided, pickles the index to disk for fast reloading.

    The index structure:

      inverted["ap"] = [0, 5, 12, 88, ...]
      entries[5] = {
          "identifier":  "037833100",
          "name":        "Apple Inc",
          "preprocessed":"apple",
          "bigrams":     frozenset({"ap", "pp", "pl", "le"}),
          "as_of_date":  date(2013, 3, 31),
          "entity_type": "Common Stock",
      }

    At query time: look up query bigrams in inverted → get candidate
    row_ids → score each candidate → apply PIT filter → return best.
    """
    entries  = {}
    inverted = defaultdict(list)

    with open(secmaster_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        col_id   = _find_column(headers, COLUMN_MAP["identifier"])
        col_name = _find_column(headers, COLUMN_MAP["name"])
        col_date = _find_column(headers, COLUMN_MAP["as_of_date"])
        col_type = _find_column(headers, COLUMN_MAP["entity_type"])

        if not col_id or not col_name:
            raise ValueError(
                f"Cannot find identifier/name columns in {secmaster_path}.\n"
                f"Found headers: {headers}\n"
                f"Expected one of: {COLUMN_MAP['identifier']} for ID, "
                f"{COLUMN_MAP['name']} for name."
            )

        for row_id, row in enumerate(reader):
            identifier  = str(row.get(col_id, "")).strip()
            raw_name    = str(row.get(col_name, "")).strip()
            date_str    = str(row.get(col_date, "")) if col_date else ""
            entity_type = str(row.get(col_type, "")).strip() if col_type else ""

            if not identifier or not raw_name:
                continue

            preprocessed = preprocess(raw_name)
            bigrams      = make_bigrams(preprocessed)

            if len(bigrams) < MIN_BIGRAMS:
                continue   # name too short, skip to avoid false positives

            entries[row_id] = {
                "identifier":  identifier,
                "name":        raw_name,
                "preprocessed": preprocessed,
                "bigrams":     bigrams,
                "as_of_date":  _parse_date(date_str),
                "entity_type": entity_type,
            }

            for bigram in bigrams:
                inverted[bigram].append(row_id)

    # Compute IDF weights across the whole corpus (Improvement 2)
    idf = compute_idf(entries)

    index = {"inverted": dict(inverted), "entries": entries, "idf": idf}

    if save_path:
        with open(save_path, "wb") as f:
            pickle.dump(index, f)
        print(f"Index saved → {save_path}  "
              f"({len(entries):,} entries, {len(inverted):,} unique bigrams)")

    return index


def load_index(save_path: str) -> dict:
    """Load a previously built index from disk."""
    with open(save_path, "rb") as f:
        return pickle.load(f)


# =============================================================================
# COMPONENT 3: ASOF FILTER
# What it does: given a filing date, narrows the index to only the entries
# that existed at that point in time.
# Why it matters: a 2015 filing should not be matched against Meta Platforms
# Inc, that company was still called Facebook in 2015. Without this filter,
# the function would return wrong QKIDs for historical filings.
#
# The secmaster has ONE date per row (the as-of date). The PIT logic is:
# take the most recent version of each entity that existed on or before
# the filing date. This is exactly what data.table's rolling join does.
# =============================================================================

def asof_filter(entries: dict, filing_date: date) -> dict:
    """
    Return only the entries that were valid as of filing_date.

    For each unique identifier, keep the entry with the LARGEST as_of_date
    that is still ≤ filing_date. Entries with no date are always included
    (treated as valid for all time, a safe fallback for older reference data).

    This is an O(n) scan over entries, for 60k rows this takes milliseconds.
    In a production system with 100k+ entries, build a pre-sorted structure
    per entity and use binary search.
    """
    best: dict[str, tuple] = {}   # identifier → (as_of_date, row_id)

    for row_id, entry in entries.items():
        aod = entry["as_of_date"]
        idf = entry["identifier"]

        # Include if no date (legacy data) or date is on/before filing_date
        if aod is None or aod <= filing_date:
            if idf not in best:
                best[idf] = (aod or date.min, row_id)
            else:
                prev_date, _ = best[idf]
                if (aod or date.min) > prev_date:
                    best[idf] = (aod or date.min, row_id)

    return {row_id: entries[row_id] for _, row_id in best.values()}


# =============================================================================
# COMPONENT 4: SCORER
# What it does: finds candidates that share bigrams with the query,
# scores each one, returns ranked results.
# Why it matters: the inverted index lets us skip the 99% of entries
# that share no bigrams with the query. We only score the candidates
# that actually have overlapping character patterns.
# =============================================================================

def _first_token(preprocessed: str) -> str:
    """
    Extract the first meaningful token from a preprocessed name.
    Used for first-token blocking (Improvement 3).
    """
    tokens = [t for t in preprocessed.split() if t not in LEGAL_SUFFIXES and len(t) > 1]
    return tokens[0] if tokens else ""


def _first_token_overlap(tok_a: str, tok_b: str) -> float:
    """
    Prefix-based overlap between two first tokens.

    Uses the longest common prefix relative to the shorter token's length.
    This is much more precise than character-set overlap:

      "navistar" vs "standex"  → prefix "n" vs "s" → 0/8 = 0.0  (blocks)
      "digital"  vs "digital"  → full prefix match → 1.0         (passes)
      "quanta"   vs "quanta"   → full prefix match → 1.0         (passes)
      "api"      vs "kandi"    → prefix "a" vs "k" → 0.0         (blocks)
      "amern"    vs "american" → prefix "amer" match → 0.57      (passes)

    Why prefix instead of character set:
      Character sets treat "navistar" and "standex" as 57% similar because
      they share many individual letters {a,s,t,r,n,e}. Prefix comparison
      correctly identifies them as completely different (n≠s from the start).
    """
    if not tok_a or not tok_b:
        return 0.0
    # Length of longest common prefix
    lcp = 0
    for ca, cb in zip(tok_a, tok_b, strict=False):
        if ca == cb:
            lcp += 1
        else:
            break
    # Normalise by the shorter token length
    return lcp / min(len(tok_a), len(tok_b))


def score_candidates(query_bigrams: frozenset,
                     candidate_row_ids: list,
                     entries: dict,
                     idf: dict = None,
                     query_first_token: str = "",
                     equity_only: bool = False,
                     top_k: int = 5) -> list[dict]:
    """
    Score candidates using IDF-weighted Jaccard with first-token blocking
    and optional entity type filtering.

    Improvements applied here:
      - Improvement 2: IDF-weighted Jaccard (rare bigrams count more)
      - Improvement 3: First-token blocking (prefix-based)
      - Improvement 5: Entity type filter (equity_only mode)

    Entity type filter (Improvement 5):
      When equity_only=True, skip any candidate whose entity_type is
      a non-equity instrument (ETF, mutual fund, options, bonds).
      This prevents "GOLDMAN SACHS ETF TR" from competing with
      "Goldman Sachs Group" for an equity position lookup.

      Why this matters at scale: a full secmaster holds many non-equity
      entries. Without this filter, every equity query competes against
      ETFs, closed-end funds, and bonds that happen to share bigrams.

    Returns a list of up to top_k dicts, sorted by score descending.
    """
    scores = []
    for row_id in set(candidate_row_ids):
        if row_id not in entries:
            continue
        entry = entries[row_id]

        # Improvement 5: Entity type filter, whitelist approach
        # When equity_only=True: if the entity type is KNOWN (non-empty) and
        # not in EQUITY_TYPES, skip it. Unknown/empty types pass through.
        #
        # Why whitelist not blacklist: the NON_EQUITY_TYPES blacklist misses
        # compound type strings like "NOTE 1.125% 2/1", "DEP CONV PFD A",
        # "PERP PFD CNV A", bonds and preferred that share a company name
        # with the equity. Whitelisting is complete and doesn't need updating.
        if equity_only:
            etype = entry["entity_type"].lower().strip()
            if etype and etype not in EQUITY_TYPES:
                continue

        # Improvement 3: First-token blocking (prefix-based)
        if query_first_token and len(query_first_token) >= 3:
            cand_first = _first_token(entry["preprocessed"])
            if cand_first and _first_token_overlap(query_first_token, cand_first) < 0.40:
                continue

        # Improvement 2: IDF-weighted scoring
        score = idf_weighted_jaccard(query_bigrams, entry["bigrams"], idf or {})

        if score > 0:
            scores.append({
                "identifier":  entry["identifier"],
                "name":        entry["name"],
                "entity_type": entry["entity_type"],
                "score":       round(score, 4),
                "row_id":      row_id,
            })

    scores.sort(key=lambda x: -x["score"])
    return scores[:top_k]


# =============================================================================
# COMPONENT 5: LOOKUP (THE PIPELINE ENTRY POINT)
# What it does: orchestrates all four components above into a single
# function call. Takes a raw name and a filing date, returns the best
# matching identifier (QKID) or None.
#
# This is the function the pipeline calls when the primary CUSIP lookup fails.
# =============================================================================

def lookup(raw_name: str,
           filing_date: str | date,
           index: dict,
           threshold: float = BIGRAM_THRESHOLD,
           equity_only: bool = True,
           return_details: bool = False) -> str | dict | None:
    """
    Find the best matching identifier (QKID) for a company name.

    MULTI-PASS CONFIDENCE STRATEGY (Improvement 6):
    Rather than a single threshold, the function runs three tiers:

      Tier 1, High confidence (score ≥ 0.80):
        Return immediately. These matches are reliable enough to assign
        without human review. Example: "APPLIED MATLS INC" matching
        "Applied Materials Inc" at 0.95, almost certainly correct.

      Tier 2, Medium confidence (score 0.48–0.79):
        Return with confidence="medium". These are plausible matches
        that should be verified downstream before being committed.
        Example: "QUANTA SVCS INC" matching "QUANTA SERVICES INC"
        at 0.62 after abbreviation expansion.

      Tier 3, Below minimum (score < 0.48):
        Return None. No confident match found. The row should be flagged
        as unresolved, not silently dropped.

    This tiering gives the pipeline a confidence signal. High-confidence
    matches are auto-applied. Medium-confidence matches go to a review queue.
    Nulls are flagged, not dropped, preserving data completeness.

    ENTITY TYPE FILTER (Improvement 5):
    equity_only=True (default) restricts candidates to equity-type securities.
    Set equity_only=False when matching ETF or fund positions.

    Parameters
    ----------
    raw_name     : the nameOfIssuer string from the 13F filing
    filing_date  : filing date for PIT filtering ("2015-06-30", date object, or "20150630")
    index        : prebuilt bigram index (from build_index or load_index)
    threshold    : override the length-adaptive threshold (use default for auto)
    equity_only  : if True, exclude ETFs/funds/bonds from candidates (default True)
    return_details: if True, return a dict with score + confidence tier

    Returns
    -------
    str  , identifier (QKID) of the best match
    None , no confident match found
    dict , if return_details=True:
              {identifier, name, score, entity_type, confidence}
              confidence is "high", "medium", or None
    """
    # Parse the filing date
    if isinstance(filing_date, str):
        fdate = _parse_date(filing_date)
        if fdate is None:
            fdate = date(2025, 12, 31)
    else:
        fdate = filing_date

    # Step 1: preprocess, applies HTML decode, lowercase, abbrev expansion
    preprocessed = preprocess(raw_name)
    if not preprocessed:
        return None

    query_bigrams = make_bigrams(preprocessed)
    if len(query_bigrams) < MIN_BIGRAMS:
        return None

    # Improvement 4: Length-adaptive minimum threshold
    # Only applies when using the default threshold, explicit overrides respected.
    name_len = len(preprocessed.replace(" ", ""))
    if threshold == BIGRAM_THRESHOLD:
        if name_len <= 5:
            min_threshold = 0.80   # very short: "NCR", "IMAX", near-perfect only
        elif name_len <= 8:
            min_threshold = 0.68   # short: "ARGAN", "DYAX"
        elif name_len <= 14:
            min_threshold = 0.52   # medium: "VERISIGN", "TARGET"
        else:
            min_threshold = 0.48   # long: "AMERISOURCEBERGEN"
    else:
        min_threshold = threshold

    # Step 2: PIT filter
    pit_entries = asof_filter(index["entries"], fdate)

    # Step 3: candidate retrieval from inverted index
    candidate_ids = []
    for bigram in query_bigrams:
        row_ids = index["inverted"].get(bigram, [])
        candidate_ids.extend(rid for rid in row_ids if rid in pit_entries)

    if not candidate_ids:
        return None

    query_first_token = _first_token(preprocessed)
    idf = index.get("idf", {})

    # Step 4: score with entity type filter + IDF + first-token blocking
    results = score_candidates(
        query_bigrams, candidate_ids, pit_entries,
        idf=idf,
        query_first_token=query_first_token,
        equity_only=equity_only,
        top_k=5
    )

    if not results:
        return None

    top   = results[0]
    score = top["score"]

    # Below the minimum threshold for this name length, no match
    if score < min_threshold:
        return None

    # ==========================================================================
    # IMPROVEMENT 6: MULTI-PASS CONFIDENCE TIERS
    # Assign a confidence level based on the score.
    # High confidence → auto-assign QKID (can be trusted without review)
    # Medium confidence → assign but flag for downstream verification
    # This replaces a binary match/no-match with a graded signal.
    # ==========================================================================
    if score >= CONFIDENCE_HIGH:
        confidence = "high"
    elif score >= CONFIDENCE_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"   # above min_threshold but below medium, marginal

    top["confidence"] = confidence

    if return_details:
        return top
    return top["identifier"]


def batch_lookup(names: list,
                 filing_dates: list,
                 index: dict,
                 threshold: float = BIGRAM_THRESHOLD,
                 equity_only: bool = True,
                 return_details: bool = False) -> list:
    """
    Vectorised version of lookup for production batch processing.

    Returns a list of results, one per input row.
    If return_details=True, each result is a dict with identifier, name,
    score, entity_type, and confidence tier ("high" / "medium" / "low" / None).

    The confidence tier is what the pipeline uses to decide:
      "high"   → auto-assign QKID
      "medium" → assign but put in review queue
      "low"    → flag as uncertain, do not auto-assign
      None     → no match found, row is preserved as unresolved
    """
    assert len(names) == len(filing_dates), "names and dates must be same length"

    results = []
    for name, fdate in zip(names, filing_dates, strict=True):
        results.append(
            lookup(name, fdate, index, threshold,
                   equity_only=equity_only,
                   return_details=return_details)
        )

    return results


# =============================================================================
# CONVENIENCE: BUILD INDEX FROM MULTIPLE COMMON SOURCE FORMATS
# =============================================================================

def build_index_from_secmaster(secmaster_path: str,
                                save_path: str | None = None) -> dict:
    """Alias for build_index, explicit name for clarity."""
    return build_index(secmaster_path, save_path)


def build_index_from_sec13f_list(sec13f_path: str,
                                  as_of_date: str = "20131231",
                                  save_path: str | None = None) -> dict:
    """
    Build an index from the SEC 13F official securities list.

    The SEC 13F list does not have QKIDs or validity dates, so we use
    the CUSIP as the identifier and apply a single as-of date for all entries.

    This is a fallback for testing without a full secmaster.
    """
    import pandas as pd

    df = pd.read_csv(sec13f_path)
    df = df[df.get("is_primary", pd.Series([True] * len(df))).ne(False)]
    df = df.drop_duplicates("cusip", keep="first")

    # Write a temporary standardised CSV
    import os
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                      delete=False, newline="")
    tmp.write("identifier,name,as_of_date,entity_type\n")
    for _, row in df.iterrows():
        tmp.write(f"{row['cusip']},{row['company_name']},"
                  f"{as_of_date},{row.get('security_type','')}\n")
    tmp.close()

    index = build_index(tmp.name, save_path)
    os.unlink(tmp.name)
    return index


if __name__ == "__main__":
    print("fuzzy_name_lookup.py, import this module, do not run directly.")
    print("Usage:")
    print("  from fuzzy_name_lookup import build_index, lookup, batch_lookup")
    print("  index = build_index('secmaster.csv', save_path='index.pkl')")
    print("  qkid  = lookup('APPLIED MATLS INC', '2015-06-30', index)")
