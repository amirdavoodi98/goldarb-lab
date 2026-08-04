# `fetch_data`

Small, login-aware fetch scripts for pulling live and near-live data from `goldarb.ir`.

## Setup

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

If `GOLDARB_TOKEN` is present, it is used directly.
Otherwise, the client logs in with `GOLDARB_USERNAME` and `GOLDARB_PASSWORD`.

## Install

Use the project virtualenv:

```bash
./venv/bin/pip install -r requirements.txt
```

## Run all fetches

```bash
./venv/bin/python -m fetch_data.run_all
```

This logs in once and prints each result in sequence.

## Scripts

Each script prints the raw Python object returned by the SDK.

| Script | What it fetches | What it returns |
|---|---|---|
| `fetch_fund_holding.py` | Latest fund portfolio composition | `dict` from `client.fund.holdings(symbol)` |
| `fetch_fund_issue_unit.py` | Fund issued/outstanding units | `dict` from `client.fund.issued_units(symbol)` |
| `fetch_usdt_live.py` | USDT/IRT live tip | `dict` from `client.market.usdt_live()` |
| `fetch_gold_coin_live.py` | IME CDC GoldCoin live data | `dict` from `client.market.ime_cdc_live("GoldCoin")` |
| `fetch_goldbar_live.py` | IME CDC GoldBar live data | `dict` from `client.market.ime_cdc_live("GoldBar")` |
| `fetch_xau_xag_live.py` | XAU/XAG spot live snapshot | `dict` from `client.market.spot_live()` |

## Notes on the returned data

- `fetch_fund_holding.py`
  - Returns the latest composition of a fund.
  - The exact keys depend on the backend payload.
  - Use this for asset weights / portfolio breakdown.

- `fetch_fund_issue_unit.py`
  - Returns fund-level issued units.
  - This is **not** a specific investor position.
  - It is near-daily/as-of data, not tick-by-tick data.

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

All scripts use the shared client in `goldarb_client.py`.

That client:

- loads `.env`
- adds `src/` to `sys.path`
- logs in once per process
- reuses the same authenticated session

## Runner behavior

`run_all.py` uses one client instance and calls all fetch helpers directly.
That avoids repeated login requests and reduces the chance of `429 Too Many Requests`.

If the remote service is unreachable or rate-limits the login endpoint, the runner stops and prints the failing step.

