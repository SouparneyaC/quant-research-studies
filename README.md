# Quant Research Studies

Independent quantitative research on institutional holdings and market prices. One study per folder, each with its own data, code, write-up and way to reproduce it.

![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![R 4.5](https://img.shields.io/badge/R-4.5-blue)

## Overview

Each study names its data source in its own README, because the studies use different data.

- Common ownership of S&P 500 firms, replicated on 13F data, and the data repair it took
- Hedge-fund pod disagreement from 13F filings
- A Kalman-filter pairs trade on country ETFs
- A tested Python package for 13F work: ownership overlap, data-quality checks and company-name matching

Currently included studies:

| Study | Question | Data | Write-up |
|---|---|---|---|
| [Common Ownership](studies/common-ownership/) | How much do competing S&P 500 firms share the same owners, 2013 to 2025, and what does it take to get clean data? | QuantKiosk 13F holdings (key needed, not included) and SEC XBRL | [Report](studies/common-ownership/Common_Ownership_Analysis_Report.pdf) |
| [Intra-Firm Divergence](studies/pod-divergence/) | Do the pods inside a multi-strategy hedge fund hold opposite sides of the same stock, and what does that signal? | QuantKiosk 13F submanager holdings (D.E. Shaw sample, no key needed) | [Paper](studies/pod-divergence/Intra-Firm-Divergence-as-a-Volatility-Predictor.pdf) |
| [Adaptive Pairs Trading](studies/adaptive-pairs-trading/) | Does a time-varying hedge ratio with a Random Forest entry gate help an EWA/EWC pairs trade through a structural break? | Yahoo Finance prices, 2020 to 2025 | [Paper](studies/adaptive-pairs-trading/paper.pdf) |

## Results

| Study | Result |
|---|---|
| Common Ownership | Mean ownership overlap (kappa) rose from about 0.71 to about 0.92 over 48 firms and 50 quarters (112,800 values). The Big Three account for about 78% of it. The data needed eight repairs and one partial vendor gap |
| Intra-Firm Divergence | In D.E. Shaw's Q1 2024 filings (6,482 position rows), Celsius (CELH) showed a 20,674.8% spread between its most-buying and most-selling pod, Microchip (MCHP) 2,168.3% and Nvidia (NVDA) 56.7% |
| Adaptive Pairs Trading | Sharpe ratio 0.36 over 72 active trading days, most of the return earned by staying out of the market during the 2024 divergence between EWA and EWC |

The package tests (`pytest`) check the kappa identities, the data-quality checks and the name matcher on synthetic data. The pairs-trading result was reproduced for this repository by running `oil_copper_fitted_ML.py`, which prints a final Sharpe ratio of 0.36 and 72 trade days. The Intra-Firm Divergence tables are the paper's figures. How far each can be re-run, and where it cannot, is in the study's own README.

## Installation & Usage

The package and its tests (Python 3.11 or later, no data and no key needed):

```bash
python3 -m venv venv
venv/bin/pip install -e ".[dev]"
venv/bin/pytest
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

then follow the usage section in [studies/pod-divergence/README.md](studies/pod-divergence/README.md).

## Project Structure

```
├── src/qk13f/                   # tested package: kappa, data-quality checks, name matching
├── tests/                       # unit tests on synthetic data
├── studies/
│   ├── common-ownership/        # replication, results, data-quality record (Python)
│   ├── pod-divergence/          # Friction Index scanner, charts, results, paper (R)
│   └── adaptive-pairs-trading/  # Kalman filter and Random Forest pairs trade, paper (Python)
├── LICENSE
└── CHANGELOG.md
```

## Notes

- No raw vendor data is stored here. The common-ownership study ships derived tables only, the Intra-Firm Divergence study reads the sample that ships with the `qkiosk` R package, and the pairs study downloads prices at run time.
- The scripts in each study are the record of what was run. The package in `src/qk13f` is the tested, reusable core.
- None of the studies is a trading recommendation.
- This repository is not affiliated with QuantKiosk, D.E. Shaw or Yahoo.

## Contributing

Bug reports and small pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, and [SECURITY.md](SECURITY.md) says how to report a vulnerability.

## Credits

Built by Souparneya Chakrabarti, with Claude, an AI model from Anthropic, as a coding collaborator. To cite the work, use the "Cite this repository" box on GitHub, which reads `CITATION.cff`.

## License

[MIT](LICENSE)
