# Quant Research Studies

Independent quantitative research on institutional holdings and market prices. One study per folder, each with its own data, code, write-up and way to reproduce it.

![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![R 4.5](https://img.shields.io/badge/R-4.5-blue)

## Overview

Each study names its data source in its own README, because the two studies here use different data.

- Hedge-fund pod disagreement from 13F filings
- A Kalman-filter pairs trade on country ETFs
- Reproducible scripts and the papers behind them

Currently included studies:

| Study | Question | Data | Write-up |
|---|---|---|---|
| [Intra-Firm Divergence](studies/pod-divergence/) | Do the pods inside a multi-strategy hedge fund hold opposite sides of the same stock, and what does that signal? | QuantKiosk 13F submanager holdings (D.E. Shaw sample, no key needed) | [Paper](studies/pod-divergence/Intra-Firm-Divergence-as-a-Volatility-Predictor.pdf) |
| [Adaptive Pairs Trading](studies/adaptive-pairs-trading/) | Does a time-varying hedge ratio with a Random Forest entry gate help an EWA/EWC pairs trade through a structural break? | Yahoo Finance prices, 2020 to 2025 | [Paper](studies/adaptive-pairs-trading/paper.pdf) |

## Results

| Study | Result |
|---|---|
| Intra-Firm Divergence | In D.E. Shaw's Q1 2024 filings (6,482 position rows), Celsius (CELH) showed a 20,674.8% spread between its most-buying and most-selling pod, Microchip (MCHP) 2,168.3% and Nvidia (NVDA) 56.7% |
| Adaptive Pairs Trading | Sharpe ratio 0.36 over 72 active trading days, most of the return earned by staying out of the market during the 2024 divergence between EWA and EWC |

The pairs-trading result was reproduced for this repository by running `oil_copper_fitted_ML.py`, which prints a final Sharpe ratio of 0.36 and 72 trade days. The Intra-Firm Divergence tables are the paper's figures. How far each can be re-run, and where it cannot, is in the study's own README.

## Installation & Usage

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
├── studies/
│   ├── pod-divergence/          # Friction Index scanner, charts, results, paper (R)
│   └── adaptive-pairs-trading/  # Kalman filter and Random Forest pairs trade, paper (Python)
├── LICENSE
└── CHANGELOG.md
```

## Notes

- No vendor data is stored here. The Intra-Firm Divergence study reads the sample that ships with the `qkiosk` R package, and the pairs study downloads prices at run time.
- Neither study is a trading recommendation.
- This repository is not affiliated with QuantKiosk, D.E. Shaw or Yahoo.

## Contributing

Bug reports and small pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, and [SECURITY.md](SECURITY.md) says how to report a vulnerability.

## Credits

Built by Souparneya Chakrabarti, with Claude, an AI model from Anthropic, as a coding collaborator. To cite the work, use the "Cite this repository" box on GitHub, which reads `CITATION.cff`.

## License

[MIT](LICENSE)
