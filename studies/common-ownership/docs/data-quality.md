# Data quality

The holdings and share counts came from a data vendor's API and from SEC XBRL filings. They were not clean. This file lists what was found and how each fault was recognised. The checks are also in `qk13f.quality`, tested on synthetic data.

## The catalogue

| Firm and quarter | Cause | Fix |
|---|---|---|
| Visa | No XBRL share data for any of 50 quarters | Left out of the panel |
| AAPL 2014 Q1 | XBRL units error: shares reported about 1,000 times too large | Scale correction |
| KO 2018 Q1 to Q3, 2019 Q1 | XBRL units error: about 1,000,000 times too large | Scale correction |
| NVDA 2021 Q2 | Stock-split timing mismatch | Split adjustment |
| NVDA 2014 to 2016 | Convertible-bond holdings inflated institutional ownership | Scale factor, not exclusion, because the quarter is still needed |
| MA 2013 Q4 | A 10-K filed after the January 2014 10-for-1 split restated shares for an earlier quarter | Divide by 10 |
| WMT 2023 Q4 | Same pattern after a 3-for-1 split in February 2024 | Divide by 3 |
| BlackRock (CIK 2012383), every ticker, 2025 Q4 | The original 13F and a later amendment were both ingested and summed, so holdings exactly doubled | Halve that filer's holdings for the quarter |

A ninth fault, State Street in 2015, is below.

## How each was recognised

Every fault had a signature that a plain data check can find:

| Signature | Check |
|---|---|
| Adjacent quarters differ by exactly a known split ratio | `matches_split_ratio` |
| A value is about 1,000 or 1,000,000 times its neighbour | `scale_error_factor` |
| One filer's holdings exactly double for every ticker | `is_doubled` |
| Institutions hold more than 100% of a company | `exceeds_full_ownership` |
| A filer reports 70 to 90% of the expected level | `is_partial_gap` |

The last two matter because they are easy to talk yourself out of. Over 100% ownership usually means convertible bonds are reported with the equity, which calls for a scale factor, not for dropping the quarter. A partial gap looks plausible on a quick check, so it needs an explicit ratio to expected holdings.

## State Street, 2015 Q2 and Q3

State Street's reported holdings sat at about 72% of the expected level for two quarters. This is a partial gap, which is harder to find than a quarter with nothing in it.

1. **Attribution.** The data was compared with the SEC's own EDGAR filings (`data_quality/audit_statestreet_2015_edgar_vs_qk.py`). EDGAR showed complete filings, so the gap was in the vendor's ingestion and not in this pipeline or a missing amendment.
2. **Repair.** A single scale factor for the whole filer was too crude, so the repair used EDGAR values where they were available and per-ticker interpolation between 2015 Q1 and Q4 elsewhere. One position, AIG, was left at its EDGAR value, because State Street really did cut it from about 59 million shares to about 30 thousand in that quarter.
3. **Reproducibility.** An amendment ingested later can change what the vendor returns for the same quarter. Every data pull is dated, so a manual fix can be reversed once the vendor's data corrects itself.

## What this does not claim

- The detection functions in `qk13f.quality` were written after the fixes, from the patterns above. The repairs themselves were applied by hand to the processed tables, and the factors are in `results/contaminated_quarters.csv`.
- Thresholds such as 2% for a split ratio and 0.9 for a partial gap are choices, not measurements.
