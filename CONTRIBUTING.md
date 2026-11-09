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

## Typed domain contracts

Core models use immutable dataclasses, and service boundaries use structural
`Protocol` interfaces. Dependencies are supplied through constructors or the
runner's existing setters. Implementing a protocol does not require inheriting
from it or registering with a dependency-injection container.

Signal consumers inside the application should use the domain APIs:

```python
from goldarb.signals import evaluate_rankings

result = evaluate_rankings({"A": [0.0, -2.0], "B": [0.0, 2.0]}, min_samples=2)
if result.best_pair is not None:
    symbol = result.best_pair.long_symbol
payload = result.to_dict()  # Explicit conversion for JSON or external consumers.
```

`evaluate_pair_spread` likewise returns an immutable result with a typed
`pair_signal`. The legacy `compute_rankings` and `compute_pair_spread_stats`
functions, and strategy `last_ranking` / `last_stats` attributes, retain their
dictionary contracts. Keep dynamic API payloads as dictionaries until their
schema is known; do not infer a domain model from one observed response.

Gateway hooks (`AccountBinding`, `MarketObserver`, `DeferredFills`) and broker
capabilities (`ConfigurableExecution`, `DelayedOrderSettlement`) are separate
protocols so an implementation only needs the capabilities it actually offers.
The paper gateway base class is generic in its broker type; local and remote
adapters retain their specific submit contracts.

Run static checks with:

```bash
pip install -e ".[dev]"
mypy
```

CI requires strict type checking for signal models, execution interfaces,
gateways, the engine, strategy context, runtime, configuration, and data sources.
The explicit file list is in `pyproject.toml`. `tests/typing/contracts.py` also
checks that local, remote, recording, and fund implementations satisfy their
interfaces without constructing clients or sending requests. The checked mypy
version is pinned in the development dependencies.

Feed contracts live in `goldarb.feed_contracts`. Historical-only endpoints need
only `candles_many`; live endpoints provide `last_price`, `orderbook`, and
`candles`. Bulk candles, prices, NAVs, and orderbooks are independent optional
capabilities. The runner validates the capability needed by its selected mode;
it accepts either a fund endpoint or a client exposing `.fund`. External row
columns and custom strategy/model parameters remain dynamic mappings.

Configuration files are parsed into the existing `AppConfig` dataclasses.
`SessionConfig.resolve_schedule()` converts timezone and clock strings into an
immutable `SessionSchedule` for provider code. Builder setters retain the
original Ellipsis sentinel: omitting a nullable argument preserves it, while
passing `None` clears it. The sentinel now has an explicit type.

This coverage is an incremental baseline, not a claim that the entire SDK is
strictly checked. The optional YAML dependency is untyped; its output still
passes through the configuration parser. Unit tests and Ruff remain separate
checks.
