# goldarb-lab — Strategy Lab SDK

Python client for **historical + live tip** series from the Gold Arbitrage
platform. Install and use without the Django monorepo.

## Install

```bash
git clone https://github.com/amirdavoodi98/goldarb-lab.git
cd goldarb-lab
pip install -e ".[pandas,dev]"
```

## Auth

| Variable | Meaning |
|----------|---------|
| `GOLDARB_BASE_URL` | Platform origin, **no trailing slash** (e.g. `https://goldarb.ir`) |
| `GOLDARB_TOKEN` | DRF token from `POST /api/v1/auth/token/` |

```bash
export GOLDARB_BASE_URL=https://goldarb.ir
export GOLDARB_TOKEN=xxxxxxxx
```

Or:

```python
from goldarb import LabClient
c = LabClient.login(base_url="https://goldarb.ir", username="...", password="...")
```

## What strategies need

| Lab template / use | Primary series | SDK |
|--------------------|----------------|-----|
| bubble_rank / premium_threshold / basket | fund close + premium | `fund.candles` / `candles_many` |
| pair_zscore | pairwise premium z | `fund.spreads` |
| nav_model_composite | premium bands + gold18 + fair NAV | `fund.premium_stats`, `market.gold_daily`, `fund.fair_nav` |
| flow_divergence | institutional buy/sell vol | `fund.flow` |
| FX / spot overlay | XAU 1m, USDT/IRT 1m | `market.xau`, `market.usdt` |
| IME CDC (شمش/سکه/نقره) | live tip + daily stats | `market.ime_cdc_live`, `ime_cdc_stats` |
| paper-live / signal gate | live tip + orderbook | `market.live_snapshot`, `fund.orderbook` |

## Quick start — premium_threshold backtest

```python
from datetime import date, timedelta
from goldarb import LabClient, run_premium_threshold

end = date.today()
start = end - timedelta(days=89)

with LabClient.from_env() as c:
    bars = c.fund.candles("طلا", start=start.isoformat(), end=end.isoformat(), grain="daily")

result = run_premium_threshold(bars)  # buy ≤ -2%, sell ≥ +2%, next_bar fill
print(result.summary())
```

CLI example:

```bash
export GOLDARB_BASE_URL=https://goldarb.ir
export GOLDARB_TOKEN=...
python examples/backtest_premium_threshold.py
```

## Quick start — data fetch

```python
from goldarb import LabClient

with LabClient.from_env() as c:
    bars = c.fund.candles("طلا", start="2026-07-01", end="2026-07-03", grain="1m")
    flow = c.fund.flow("طلا", days=90)
    xau = c.market.xau(start="2026-07-01", end="2026-07-03", grain="1m")
    # USDT/IRR 1m — prices in **toman** (source may be import|nobitex)
    usdt = c.market.usdt(start="2026-07-01", end="2026-07-03")
    tip = c.market.usdt_live()
    units = c.fund.issued_units("طلا")  # near-daily as-of — not tick-live
    silver = c.market.ime_cdc_stats("SilverBar", days=90)  # daily CDC (may include import)
    stats = c.fund.premium_stats("طلا", window=90)
    spreads = c.fund.spreads(window=90)
    snap = c.market.live_snapshot(include=("refs", "funds", "orderbook"))
```

With pandas: `candles_df`, `flow_df`, `xau_df`, `usdt_df`, `gold_daily_df`.

### Units & freshness notes

| Series | Unit / grain | Caveat |
|--------|--------------|--------|
| `market.usdt` / `usdt_live` | **toman** (Nobitex Rials÷10 on write) | History via `?days≤31`; `source` may be `import` (ops CSV) or `nobitex`; live tip is platform Redis/`UsdtLive` |
| `fund.candles(…, grain="daily")` | close + `nav_price` / premium | Offline NAV CSV attach fills historical `nav_price` on existing days (platform ops) |
| `market.ime_cdc_stats` | daily CDC aggregates | Catalogue codes `GoldBar` / `GoldCoin` / `SilverBar`; history may include ops `source=import` |
| `fund.issued_units` / `nav_live.units` | count + `units_deven` YYYYMMDD | Near-daily as-of from TSETMC — **not** intraday; ≠ Codal `legs[].quantity` |

Ingestion (CSV/JSON manage.py importers) lives on the **platform**, not this SDK — see
platform `docs/ops/offline-csv-import.md`.

Examples:

```bash
python examples/fetch_tala_1m.py
python examples/fetch_xau.py
python examples/fetch_usdt.py
python examples/fetch_issued_units.py
python examples/strategy_data_bundle.py
python examples/backtest_premium_threshold.py
```

## API surface (v0.5)

**Strategies:** `run_premium_threshold` (offline Lab `premium_threshold` clone)

**Fund:** `candles`, `candles_many`, `candles_df`, `meta`, `symbols`, `list_symbols`,
`comparison`, `flow`, `bubbles`, `spreads`, `premium_stats`, `holdings`,
`holdings_all`, `fair_nav`, `orderbook`, `orderbooks`, `last_price`, `last_prices`,
`nav_live`, `navs_live`, `issued_units`

**Market:** `xau`, `xag`, `xau_df`, `gold_daily`, `gold_daily_df`, `usdt`, `usdt_df`,
`usdt_live`, `ime_cdc_live`, `ime_cdc_stats`, `ime_cdc_arbitrage`, `live_snapshot`,
`refs_live`, `spot_live`

## API limits

| Endpoint | Limit per request | SDK behavior |
|----------|-------------------|--------------|
| Fund bars `grain=1m` | max **7** calendar days | auto-chunks |
| Fund bars `grain=daily` | max **366** days | auto-chunks |
| Metal bars (XAU/XAG 1m) | max **31** days | auto-chunks + pagination |
| USDT 1m | max **31** days lookback | `start`/`end` chunks + filter; or `days=` |

Metal/USDT rows include both `close_price` and aliased `close` (same for O/H/L).

## Develop / test

```bash
pip install -e ".[dev]"
pytest
```

## Non-goals

- Scrapers / Celery / ingestion
- Writing to the platform DB
- Live order placement / replacing F-10 Lab UI

See [CONTRIBUTING.md](CONTRIBUTING.md).
