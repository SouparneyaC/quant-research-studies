# Contributing

Bug reports, documentation fixes and small pull requests are welcome.

## Setup

Each study is self-contained. Follow the usage section of the study's own README.

- Package and tests: Python 3.11 or later, `pip install -e ".[dev]"`, then `ruff check .` and `pytest`
- `studies/adaptive-pairs-trading`: Python 3.12, `pip install -r requirements.txt`
- `studies/citadel-lag-backtest`: Python, `pip install -r requirements.txt`, then `python analysis.py`
- `studies/amendment-disclosure`: Python, `pip install -r requirements.txt` (needs a QuantKiosk key to re-run from raw data)
- `studies/pod-divergence`, `studies/deadline-filers`: R, with the `qkiosk` package installed from GitHub (the second needs a key to re-run)

## What fits

- Fixes to the scripts and the READMEs, with the command you ran to check the change.
- New studies as a new folder under `studies/`, with a README that names the data source, says how to reproduce the result and states what the result cannot show.

## What does not

- Vendor data, raw holdings files or API keys.
- Third-party papers or datasets. Link to them instead.
- Code that places orders.
