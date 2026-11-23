# Entity resolution

13F filings identify a security by CUSIP and by the issuer's name as the filer typed it. The vendor maps a CUSIP to its own identifier. When the CUSIP is corrupted, that lookup fails and the row is dropped without a message.

## The problem

CUSIPs were corrupted in three ways: integer coercion stripped leading zeros, some were stored in scientific notation, and notation failures such as `876E110` stood in for `TARGET CORP`. Tickers were also recycled: a ticker looked up today can belong to a different company than the one that filed.

## The matcher

`qk13f.resolve` is a second path for when the CUSIP lookup fails. It searches a security master by company name.

1. **Normalise.** Decode HTML entities, lowercase, drop punctuation and trailing legal suffixes, and expand filing abbreviations, so `APPLIED MATLS INC` and `Applied Materials Inc` both become `applied materials`.
2. **Character bigrams.** Compare names by the two-letter pieces they share. This survives truncation (`AUTOMATIC DATA PROCESSING IN`) where word matching does not.
3. **IDF weighting.** Bigrams that appear in many names count for less. A plain overlap scores `CDK GLOBAL` against `RB GLOBAL` as a close match, because of the shared word `global`. The weighted score separates them.
4. **As-of date.** A 2015 filing can only match companies in the master as of 2015.
5. **Equity filter.** Equity-type entries only, so `GOLDMAN SACHS ETF TR` cannot compete with `Goldman Sachs Group` for an equity position.
6. **Confidence tiers.**

| Score | Result |
|---|---|
| 0.80 or more | Assign automatically |
| 0.48 to 0.80 | Send to a review queue |
| Below 0.48 | Leave unresolved, flagged and not dropped |

Very short names (`NCR`, `IMAX`) need a near-perfect match before they resolve.

## Test on State Street 2015

The matcher was run on a batch of 63 corrupted State Street CUSIPs from 2015 Q2 and Q3 (`data_quality/build_cusip_corruption_testset.py`).

| | Result |
|---|---|
| Recovered at `min_bigram=2` | about 60 of 63 |
| Recovered at `min_bigram=1` | 61 of 63 |
| False positives | 0 |
| Precision on a 74-ticker cross-company set | 100% (`data_quality/test_false_positives_thorough.py`) |

The two unresolved rows are bond instruments, left unresolved on purpose.

## A point-in-time bug found along the way

Looking up the ticker ALTR today returns Altair Engineering, the current owner of that ticker. A 2015 filing meant Altera Corp. The vendor's ticker resolver had no date parameter, so it could not answer as of a filing date. This is an open gap on the vendor's side as well as a client-side problem, and it is why the matcher filters by an as-of date.

## Limits

- The results above are from the author's own test batch, and the scripts are included as the record. They need the original data to run.
- Further tuning of the matcher had low marginal value. Most of the remaining missing rows came from delisted tickers that the vendor's upstream mapping changes.
- `load_index` reads a pickle file. Only load indexes you built yourself.
