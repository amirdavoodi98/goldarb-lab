# goldarb-lab

`goldarb-lab` is a Python SDK and data-collection toolkit for the Gold Arbitrage platform.

Use it to:

- fetch fund market data
- fetch IME CDC data
- fetch USDT, XAU, and XAG data
- collect missing history into local archives
- build analysis-ready merged files

## What this repo contains

- `src/goldarb` - the Python SDK
- `fetch_data` - data collectors and archive builders
- `examples` - small usage examples
- `archive` - raw history and snapshot files
- `merged_output` - combined CSV files for analysis
- `tests` - automated checks

## Install

```bash
git clone https://github.com/amirdavoodi98/goldarb-lab.git
cd goldarb-lab
pip install -e ".[pandas,dev]"
```

If you only want the runtime SDK:

```bash
pip install -e .
```

## Authentication

The client reads these environment variables:

- `GOLDARB_BASE_URL`
- `GOLDARB_TOKEN`

Or, if you do not have a token:

- `GOLDARB_BASE_URL`
- `GOLDARB_USERNAME`
- `GOLDARB_PASSWORD`

Example:

```bash
export GOLDARB_BASE_URL=https://goldarb.ir
export GOLDARB_TOKEN=your_token_here
```

## Quick start

```python
from goldarb import LabClient

with LabClient.from_env() as client:
    bars = client.fund.candles("طلا", start="2026-07-01", end="2026-07-03", grain="1m")
    holdings = client.fund.holdings("طلا")
    units = client.fund.issued_units("طلا")
    usdt = client.market.usdt_live()
    xau = client.market.xau(start="2026-07-01", end="2026-07-03", grain="1m")
    ime = client.market.ime_cdc_stats("GoldBar", days=180)
```

## Main SDK data

### Fund data

- `fund.candles(symbol, start, end, grain="1m"|"daily")`
- `fund.candles_many(symbols, start, end, grain="daily")`
- `fund.flow(symbol, days=...)`
- `fund.spreads(window=...)`
- `fund.premium_stats(symbol, window=...)`
- `fund.holdings(symbol)`
- `fund.holdings_all()`
- `fund.issued_units(symbol)`
- `fund.nav_live(symbol)`
- `fund.navs_live()`
- `fund.orderbook(symbol)`
- `fund.orderbooks()`
- `fund.fair_nav(symbol)`

### Market data

- `market.xau(start, end, grain="1m"|"daily")`
- `market.xag(start, end, grain="1m")`
- `market.usdt(start=..., end=...)`
- `market.usdt_live()`
- `market.gold_daily(days=...)`
- `market.ime_cdc_live(code)`
- `market.ime_cdc_stats(code, days=...)`
- `market.live_snapshot(include=...)`
- `market.refs_live()`
- `market.spot_live()`

## Important limits

- Fund 1m history is chunked by the SDK.
- Fund daily history is chunked by the SDK.
- XAU/XAG 1m history is chunked by the SDK.
- USDT history is limited on the platform side and is also chunked by the SDK.
- IME CDC daily history is capped at 180 days per request.

## How to collect missing data

The main collector is:

```bash
python3 -m fetch_data.collect_missing_data --days 30
```

You can use a larger window if needed:

```bash
python3 -m fetch_data.collect_missing_data --days 180
```

This collector writes append-only outputs and a coverage report.

## Collector outputs

### Raw archives

- `archive/fund_bars_1m/*.jsonl`
  - 1-minute fund bars for:
    - `عیار`
    - `طلا`
    - `کهربا`
    - `مثقال`
    - `آتش`

- `archive/holdings_history.jsonl`
  - fund holdings snapshots over time

- `archive/issued_units_history.jsonl`
  - fund issued-units snapshots over time

- `archive/ime_cdc_daily/*.jsonl`
  - daily IME CDC history for:
    - `GoldBar`
    - `GoldCoin`
    - `SilverBar`

### Missing-data collector outputs

- `archive/missing_data/fund_bars_1m/*.jsonl`
- `archive/missing_data/fund_snapshots/holdings_history.jsonl`
- `archive/missing_data/fund_snapshots/issued_units_history.jsonl`
- `archive/missing_data/ime_cdc_daily/*.jsonl`
- `archive/missing_data/coverage_report.json`
- `archive/missing_data/minute_gap_report.json`

### Merged analysis files

- `merged_output/*.csv`

These are combined files created by `fetch_data/merge_fund_datasets.py`.

They merge:

- NAV history
- portfolio composition
- available IME data
- USDT daily data
- current holdings metadata

## What the key archive files mean

### `ime_cdc_history.jsonl` and `ime_cdc_history.csv`

This is a one-time export of IME CDC daily history.

It contains normalized rows for:

- `GoldBar`
- `GoldCoin`
- `SilverBar`

Each row includes fields like:

- `contract_code`
- `trade_date`
- `last_price`
- `settlement_price`
- `trades_volume`

This file is useful for quick analysis, but it is not the long-term archive.

### `archive/ime_cdc_daily/*.jsonl`

This is the long-term IME archive.

It is better for:

- backfills
- long history
- append-only daily capture

### `archive/holdings_history.jsonl`

This stores holdings snapshots with capture time.

It is useful for point-in-time fund composition review.

### `archive/issued_units_history.jsonl`

This stores issued-units snapshots with capture time.

It is useful for NAV checks and dilution analysis.

### `archive/fund_bars_1m/*.jsonl`

This stores raw minute bars for the five funds.

It is useful for:

- minute backtests
- gap analysis
- coverage reporting

## Which files to use for the two shared reports

### For `accounting_nav_data_requirements_fa.docx`

Use these files and collectors:

- `archive/holdings_history.jsonl`
- `archive/issued_units_history.jsonl`
- `archive/ime_cdc_daily/*.jsonl`
- `archive/missing_data/coverage_report.json`
- `archive/missing_data/minute_gap_report.json`
- `merged_output/*.csv`

This report is mainly about:

- point-in-time holdings
- point-in-time issued units
- IME daily history
- missing metadata
- NAV accounting inputs

### For `minute_backtest_missing_data_report_fa.docx`

Use these files and collectors:

- `archive/fund_bars_1m/*.jsonl`
- `archive/missing_data/fund_bars_1m/*.jsonl`
- `archive/missing_data/minute_gap_report.json`
- `archive/missing_data/coverage_report.json`

This report is mainly about:

- minute completeness
- missing vs no-trade behavior
- synchronized five-fund frames
- reproducible backtest input coverage

## Helper scripts

### `fetch_data/run_all.py`

Runs the main fetch flows in one go.

### `fetch_data/daily_archive.py`

Saves holdings and issued-units snapshots over time.

### `fetch_data/minute_bar_archive.py`

Saves minute bars for the five funds over time.

### `fetch_data/ime_cdc_archive.py`

Keeps IME daily history growing over time.

### `fetch_data/fetch_ime_cdc_history.py`

Exports the latest IME daily history to CSV and JSONL.

### `fetch_data/collect_missing_data.py`

Collects missing data and writes coverage reports.

## Example scripts

```bash
python examples/backtest_premium_threshold.py
python examples/fetch_tala_1m.py
python examples/fetch_xau.py
python examples/fetch_usdt.py
```

## Run tests

```bash
pytest
```

## Simple usage rule

- Use `archive/` for raw historical data.
- Use `archive/missing_data/` for gap-filling and coverage checks.
- Use `merged_output/` for analysis-ready CSVs.
- Use `ime_cdc_history.*` for a simple IME export.

## Notes for the project owner

- This repo already provides a lot of the data collection pieces.
- The most important missing part is still true point-in-time history with strong coverage metadata.
- The new collector helps fill that gap, but some historical data may still be unavailable if the platform never exposed it.

