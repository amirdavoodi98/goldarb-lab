# Contributing

This repository is the Gold Arbitrage strategy lab: the `goldarb` package
(market-data client, paper broker, and Strategy engines) and the `fetch_data`
collectors.

## Do not add

- Scrapers, Celery workers, or Django / backend / frontend code
- Direct database credentials or Timescale access
- Hardcoded tokens, passwords, or production URLs

Platform API changes belong in
[gold-arbitrage](https://github.com/amirdavoodi98/gold-arbitrage). Keep this
client aligned with published API contracts and bump the package version when
endpoints change.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[pandas,yaml,dev]"
pytest
```

Optional lint:

```bash
pip install ruff
ruff check src tests examples
```

## Tests

Unit tests must stay offline (chunking + mocked HTTP). Do not call live
production APIs in CI.
