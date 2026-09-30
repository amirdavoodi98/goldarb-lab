# goldarb-lab

## Package (`src/goldarb`)

Market-data client, Strategy contract, and paper simulation.

- `client.py`, `fund.py`, `market.py`, `_http.py` — HTTP client for the platform API
- `data.py`, `sources.py`, `archive.py`, `session.py` — historical and live market feeds
- `strategy.py`, `strategies/`, `signals/` — Strategy contract, built-in strategies, signal math
- `engine.py`, `runtime.py`, `pipelines.py`, `config.py` — backtest / live loop and YAML runner
- `execution.py`, `execution_policy.py`, `gateway.py` — fee, slippage, latency, order policy, and the order gateway
- `simulation/` — local paper broker, remote paper client, broker wrappers, orders, matching, portfolio
- `premium_threshold.py`, `universe.py` — premium scan helper and the gold-fund universe

`BacktestEngine` and `LiveSimulationEngine` share one loop. Snapshots are not
rewritten there. `LocalPaperBroker` applies slippage and submit latency on the
order path.

## Collectors (`fetch_data`)

Scripts that pull history into `archive/` and build `merged_output/`.
They are not imported by the SDK.

## Examples, tests, docs

- `examples/` — runnable backtests, paper sessions, and small fetch scripts
- `tests/` — offline unit tests (`pytest`)
- `docs/` — SDK usage, simulator guide, strategy guide, and ADR 0001

## Data checked into the repo

- `archive/` — raw JSONL history and coverage reports
- `data/` — local NAV, composition, and reference CSVs
- `merged_output/` — analysis CSVs from `fetch_data/merge_fund_datasets.py`
- `ime_cdc_history.csv` / `ime_cdc_history.jsonl` — one-shot IME export
