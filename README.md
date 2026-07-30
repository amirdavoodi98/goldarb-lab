# goldarb-lab — Strategy Lab SDK

Python client for **historical** fund and spot series from the Gold Arbitrage
platform. Install and use without the Django monorepo.

## Install

```bash
git clone https://github.com/amirdavoodi98/goldarb-lab.git
cd goldarb-lab
pip install -e ".[pandas,dev]"
```

Or from a local checkout:

```bash
pip install -e ".[pandas,dev]"
```

## Auth

Env vars (required for `LabClient.from_env()`):

| Variable | Meaning |
|----------|---------|
| `GOLDARB_BASE_URL` | Platform origin, **no trailing slash** (e.g. `https://your-host`) |
| `GOLDARB_TOKEN` | DRF token from `POST /api/v1/auth/token/` |

Issue a token:

```bash
curl -X POST "$GOLDARB_BASE_URL/api/v1/auth/token/" \
  -H "Content-Type: application/json" \
  -d '{"username":"...","password":"..."}'
```

```bash
export GOLDARB_BASE_URL=https://your-host
export GOLDARB_TOKEN=xxxxxxxx
```

## Quick start

```python
from goldarb import LabClient

c = LabClient.from_env()

# 1-minute طلا candles (SDK auto-chunks if range > 7 days)
bars = c.fund.candles("طلا", start="2026-07-01", end="2026-07-03", grain="1m")

# XAU 1m (platform max 31d per request; SDK chunks)
xau = c.market.xau(start="2026-07-01", end="2026-07-03", grain="1m")

# Daily gold refs (XAU USD, 18k IRR, …)
daily = c.market.gold_daily(days=90)
```

With pandas:

```python
df = c.fund.candles_df("طلا", start="2026-07-01", end="2026-07-03", grain="1m")
```

Examples:

```bash
python examples/fetch_tala_1m.py
python examples/fetch_xau.py
```

## API limits

| Endpoint | Limit per request | SDK behavior |
|----------|-------------------|--------------|
| Fund bars `grain=1m` | max **7** calendar days | auto-chunks |
| Fund bars `grain=daily` | max **366** days | auto-chunks |
| Metal bars (XAU/XAG 1m) | max **31** days | auto-chunks + pagination |

Auth header: `Authorization: Token <key>`.

Relevant routes:

- `POST /api/v1/auth/token/`
- `GET /api/v1/funds/<symbol>/bars/?grain=1m|daily&date_from=&date_to=`
- `GET /api/v1/market/metals/bars/?symbol=XAUUSD&date_from=&date_to=`

## Develop / test

```bash
pip install -e ".[dev]"
pytest
```

## Non-goals

- Scrapers / Celery / ingestion
- Writing to the platform DB
- Live order placement

See [CONTRIBUTING.md](CONTRIBUTING.md). Platform API contracts live in
[gold-arbitrage](https://github.com/amirdavoodi98/gold-arbitrage); bump this
package version when endpoints change.
