# `fetch_data`

Utilities for fetching live and near-live market data from `goldarb.ir`.

This directory is designed to work with:

- `.env` credentials
- one shared authenticated client
- a single-command runner for all fetch flows

## Environment

Create a `.env` file in the project root:

```env
GOLDARB_BASE_URL=https://goldarb.ir
GOLDARB_USERNAME=your_username
GOLDARB_PASSWORD=your_password
```

Optional:

```env
GOLDARB_TOKEN=your_token
```

Priority:

1. `GOLDARB_TOKEN`
2. `GOLDARB_USERNAME` + `GOLDARB_PASSWORD`

## Install

Use the project virtualenv:

```bash
./venv/bin/pip install -r requirements.txt
```

## Run everything

```bash
./venv/bin/python -m fetch_data.run_all
```

This logs in once, calls every fetch helper, and prints the returned objects.

## Individual scripts

Each script prints the raw object returned by the SDK.

| Script | Returns | Meaning |
|---|---|---|
| `fetch_fund_holding.py` | `dict` | Latest fund portfolio composition / asset mix |
| `fetch_fund_issue_unit.py` | `dict` | Fund-level issued units, near-daily as-of |
| `fetch_usdt_live.py` | `dict` | Live USDT/IRT tip, unit is toman |
| `fetch_gold_coin_live.py` | `dict` | Live GoldCoin IME CDC snapshot |
| `fetch_goldbar_live.py` | `dict` | Live GoldBar IME CDC snapshot |
| `fetch_xau_xag_live.py` | `dict` | Live XAU/XAG spot snapshot |

## What each script returns

- `fetch_fund_holding.py`
  - Returns the latest holdings/composition for one fund.
  - The exact keys come from the backend payload.
  - Use this for portfolio weights and asset breakdown.

- `fetch_fund_issue_unit.py`
  - Returns fund-issued / outstanding unit information.
  - This is **not** a specific investor position.
  - It is near-daily/as-of data, not tick-live data.

- `fetch_usdt_live.py`
  - Returns the live USDT/IRT tip.
  - Values are in **toman**.

- `fetch_gold_coin_live.py`
  - Returns live GoldCoin CDC data.

- `fetch_goldbar_live.py`
  - Returns live GoldBar CDC data.

- `fetch_xau_xag_live.py`
  - Returns the live XAU/XAG spot snapshot.

## Shared client

All scripts use the shared client in [`goldarb_client.py`](../goldarb_client.py).

That client:

- loads `.env`
- adds `src/` to `sys.path`
- logs in once per process
- reuses the same authenticated session

## Runner notes

`run_all.py` uses one client instance and calls all fetch helpers directly.

That avoids repeated login requests and helps reduce the chance of `429 Too Many Requests`.

If the remote service is unreachable or rate-limits authentication, the runner stops and prints the failing step.
