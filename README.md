# goldarb-lab — Strategy team data client

Python SDK for pulling **historical** fund and spot series from the Gold Arbitrage
platform. Intended to live in a **separate GitHub repository**; this folder is the
seed package shipped inside the monorepo until that repo exists.

## Install (editable, from monorepo)

```bash
cd goldarb-lab
pip install -e ".[pandas,dev]"
```

## Auth

1. Create a platform user (Django admin / createsuperuser).
2. Issue a token:

```bash
curl -X POST "$GOLDARB_BASE_URL/api/v1/auth/token/" \
  -H "Content-Type: application/json" \
  -d '{"username":"...","password":"..."}'
```

3. Export:

```bash
export GOLDARB_BASE_URL=https://your-host   # no trailing slash
export GOLDARB_TOKEN=xxxxxxxx
```

## Quick start

```python
from goldarb import LabClient

c = LabClient.from_env()

# 1-minute طلا candles (auto-chunks if range > 7 days)
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

## Extract to own repository

```bash
# from monorepo root
mkdir -p ../goldarb-lab-repo
cp -a goldarb-lab/. ../goldarb-lab-repo/
cd ../goldarb-lab-repo
git init
# push to new empty GitHub repo
```

Keep platform API contracts stable; bump SDK version when endpoints change.

## Non-goals

- Scrapers / Celery
- Writing to the platform DB
- Live order placement
