# Quant Research Studies

Independent quantitative research on institutional holdings and market prices. One study per folder, each with its own data source, code, write-up and way to reproduce it. Several of the results are negative or confounded, and each study says so.

[![CI](https://github.com/SouparneyaC/quant-research-studies/actions/workflows/ci.yml/badge.svg)](https://github.com/SouparneyaC/quant-research-studies/actions/workflows/ci.yml)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![R 4.5](https://img.shields.io/badge/R-4.5-blue)

## Overview

Six studies and one tested Python package. Most use QuantKiosk's 13F data, which needs an API key and is not redistributed here, so each study commits its derived results and says how much of it can be re-run without the key.

| Study | Question | Data | Runs without a key | Write-up |
|---|---|---|---|---|
| [Common Ownership](studies/common-ownership/) | How much do competing S&P 500 firms share the same owners, 2013 to 2025, and what does it take to get clean data? | QuantKiosk 13F holdings and SEC XBRL | Derived results and the tested package | [Report](studies/common-ownership/Common_Ownership_Analysis_Report.pdf) |
| [13F Amendments](studies/amendment-disclosure/) | Does a fund's first 13F amendment coincide with a jump in its reported assets under management? | QuantKiosk manager-level value totals | Committed result tables | [Paper](https://souparneyac.github.io/research/strategic-disclosure/) |
| [Deadline Filers](studies/deadline-filers/) | Do funds that file their 13F on the last days trade more than funds that file early? | QuantKiosk position-level holdings | Turnover table and figures 1 to 3 | [README](studies/deadline-filers/README.md) |
| [Citadel Lag Backtest](studies/citadel-lag-backtest/) | Does buying Citadel's reported long positions on the 13F due date beat SPY? | QuantKiosk holdings, Yahoo Finance prices, Fama-French factors | All of the analysis, from committed tables | [README](studies/citadel-lag-backtest/README.md) |
| [Intra-Firm Divergence](studies/pod-divergence/) | Do the pods inside a multi-strategy hedge fund hold opposite sides of the same stock, and what does that signal? | QuantKiosk submanager holdings (D.E. Shaw sample) | The scanner, on the sample that ships with `qkiosk` | [Paper](studies/pod-divergence/Intra-Firm-Divergence-as-a-Volatility-Predictor.pdf) |
| [Adaptive Pairs Trading](studies/adaptive-pairs-trading/) | Does a time-varying hedge ratio with a Random Forest entry gate help an EWA/EWC pairs trade through a structural break? | Yahoo Finance prices, 2020 to 2025 | Everything | [Paper](studies/adaptive-pairs-trading/paper.pdf) |

The package in [`src/qk13f`](src/qk13f/) holds the reusable parts: ownership overlap (kappa) and its decomposition, data-quality checks, and fuzzy company-name matching.

## Results

| Study | Result |
|---|---|
| Common Ownership | Mean ownership overlap (kappa) rose from about 0.71 to about 0.92 over 48 firms and 50 quarters (112,800 values). The Big Three account for about 78% of it. The data needed eight repairs and one partial vendor gap |
| 13F Amendments | A one-quarter jump of 1.7 percentage points in reported AUM at a fund's first amendment (p about 0.027, 81,121 fund-quarters), gone within two quarters; the average post-amendment effect is zero |
| Deadline Filers | Three deadline filers turned over 37.7% of positions a quarter against 8.1% for two early filers (4.66 times), over 40 fund-quarters. The deadline filers are options market makers and the early filers hold no options, so the gap does not isolate the filing habit |
| Citadel Lag Backtest | The lagged copy grew 1.040 against 1.046 for SPY over the same dates (20 quarters, p = 0.96), and the holdings show no excess return over SPY at any horizon from day 1 to day 90. The first version's headline edge came from a benchmark covering half the dates and factor data one quarter out of line |
| Intra-Firm Divergence | In D.E. Shaw's Q1 2024 filings (6,482 position rows), Celsius (CELH) showed a 20,674.8% spread between its most-buying and most-selling pod, Microchip (MCHP) 2,168.3% and Nvidia (NVDA) 56.7% |
| Adaptive Pairs Trading | Sharpe ratio 0.36 over 72 active trading days, most of the return earned by staying out of the market during the 2024 divergence between EWA and EWC. The Random Forest was fitted on 80% of those days; on the last 300 days alone the Sharpe is 1.36 on 20 signal days, with or without the classifier |

How these were checked:

- `pytest` tests the kappa identities, the data-quality checks and the name matcher on synthetic data, and that the result tables committed for the amendment, deadline-filer and Citadel studies match the numbers above.
- The pairs-trading result was reproduced for this repository by running `oil_copper_fitted_ML.py`, which prints a final Sharpe ratio of 0.36 and 72 trade days; `holdout_check.py` splits it into training and held-out periods.
- The Intra-Firm Divergence tables are the paper's figures. The current `qkiosk` sample does not reproduce them, which that study's README explains.
- How far each study can be re-run, and where it cannot, is in its own README.

## Installation & Usage

The package and all the tests (Python 3.11 or later, no data and no key):

```bash
python3 -m venv venv
venv/bin/pip install -e ".[dev]"
venv/bin/pytest
```

Citadel Lag Backtest (Python, from the committed tables):

```bash
cd studies/citadel-lag-backtest
python3 -m pip install -r requirements.txt
python3 analysis.py
```

Adaptive Pairs Trading (Python 3.12, downloads prices from Yahoo Finance when it runs):

```bash
cd studies/adaptive-pairs-trading
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python oil_copper_fitted_ML.py
```

Intra-Firm Divergence (R, no API key for the sample data):

```r
remotes::install_github("quantkiosk/qkiosk-r")
```

then follow the usage section in [studies/pod-divergence/README.md](studies/pod-divergence/README.md). The other QuantKiosk studies re-run from the raw data only with a key (`QK_API_KEY`); their READMEs list the steps.

## Project Structure

```
├── src/qk13f/                   # tested package: kappa, data-quality checks, name matching
├── tests/                       # unit tests on synthetic data and on the committed result tables
├── studies/
│   ├── common-ownership/        # replication, results, data-quality record (Python)
│   ├── amendment-disclosure/    # 13F amendment event study, results, figures (Python)
│   ├── deadline-filers/         # filing lag vs turnover, five funds, figures (R)
│   ├── citadel-lag-backtest/    # lagged 13F copy vs SPY, corrected checks (Python, R fetch)
│   ├── pod-divergence/          # Friction Index scanner, charts, results, paper (R)
│   └── adaptive-pairs-trading/  # Kalman filter and Random Forest pairs trade, paper (Python)
├── LICENSE
└── CHANGELOG.md
```

## Notes

- No raw vendor data is stored here. The studies ship derived tables only, the Intra-Firm Divergence study reads the sample that ships with the `qkiosk` R package, and the pairs study downloads prices at run time.
- The scripts in each study are the record of what was run. The package in `src/qk13f` is the tested, reusable core.
- None of the studies is a trading recommendation.
- This repository is not affiliated with QuantKiosk, D.E. Shaw, Citadel or Yahoo.

## Contributing

Bug reports and small pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, and [SECURITY.md](SECURITY.md) says how to report a vulnerability.

## Credits

Built by Souparneya Chakrabarti, with Claude, an AI model from Anthropic, as a coding collaborator. To cite the work, use the "Cite this repository" box on GitHub, which reads `CITATION.cff`.

## License

[MIT](LICENSE)
