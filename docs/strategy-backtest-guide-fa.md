# راهنمای تعریف استراتژی، تنظیم کانفیگ و بک‌تست

این سند برای کسی است که می‌خواهد در `goldarb-lab` یک Strategy بنویسد، کانفیگ را تنظیم کند و بک‌تست بگیرد.

اصل کار:

> منطق سیگنال را یک‌بار بنویس. منبع داده، کارگزار و حالت اجرا را با کانفیگ عوض کن.

```text
Strategy  →  AppConfig  →  StrategyRunner  →  RunResult
```

Strategy نباید HTTP، فایل، SQLite یا API را ببیند. فقط با `StrategyContext` کار می‌کند.

نیازمندی‌ها: [`srs-sdk-v0.1.md`](srs-sdk-v0.1.md)  
مرجع API و سشن ایران: [`sdk-usage-fa.md`](sdk-usage-fa.md)  
جزئیات مچینگ سفارش: [`local-simulator-fa.md`](local-simulator-fa.md)

---

## ۱. نصب

Python **3.11** یا جدیدتر لازم است.

```bash
git clone <repo>
cd goldarb-lab
python3.11 -m venv .venv
source .venv/bin/activate
uv pip install --python .venv/bin/python -e ".[yaml,dev]"
```

اگر `uv` نداری:

```bash
python3.11 -m pip install -e ".[yaml,dev]"
```

برای YAML باید extraی `yaml` نصب شود. نصب از PyPI به‌صورت `pip install goldarb-lab[yaml]` کار نمی‌کند؛ پکیج منتشر نشده است و باید از همین ریپو نصب شود.

ورود به API فقط وقتی لازم است که از داده زنده یا دانلود آرشیو استفاده کنی:

```bash
export GOLDARB_BASE_URL=https://goldarb.ir
export GOLDARB_TOKEN=your_token_here
```

توکن را داخل فایل کانفیگ نگذار.

تست سریع نصب:

```bash
python examples/run_price_momentum_from_config.py
```

خروجی مشابه این است:

```text
strategy=price_momentum mode=offline_backtest signals=4 orders=4 fills=4 equity=...
```

---

## ۲. مسیر پیشنهادی برای شروع

1. یک آرشیو محلی داشته باش، یا از دموی کوچک استفاده کن.
2. کلاس Strategy را بنویس.
3. یک YAML بساز.
4. یک اسکریپت شبیه `examples/run_from_config.py` بنویس که کلاس Strategy را از `config.strategy.params` بسازد.
5. `StrategyRunner.from_config(config).run(strategy)` را اجرا کن.
6. `RunResult` را بخوان.

دو مثال آماده:

| کار | فرمان |
| --- | --- |
| بک‌تست حباب روی آرشیو یک‌روزه | `python examples/run_from_config.py` |
| بک‌تست مومنتوم روی دیتای خیلی کوچک | `python examples/run_price_momentum_from_config.py` |

دموی سبک مومنتوم در `examples/data/price-momentum-demo/` است و معمولاً زیر یک ثانیه تمام می‌شود.

`examples/run_from_config.py` روی `archive/1s-14d` و یک روز (`2026-09-15`) اجرا می‌شود؛ معمولاً چند ثانیه طول می‌کشد. اگر `start/end` را برداری و کل آرشیو ۱۴روزه را با SQLite فایل اجرا کنی، ممکن است خیلی کند شود.

---

## ۳. داده تاریخی

سه حالت رایج وجود دارد.

### الف) آرشیو محلی، بدون اینترنت

```yaml
data:
  provider: archive
  source: archive/1s-14d
  symbols: ["طلا", "عیار"]
  grain: 1s
  start: "2026-09-15"
  end: "2026-09-15"
  fill_session: false

runtime:
  mode: offline_backtest
```

`provider: archive` فرمت را از `manifest.json` تشخیص می‌دهد. می‌توانی صریح بنویسی `jsonl` یا `parquet`.

اگر آرشیو نداری، دانلود کن:

```python
from goldarb import LabClient, download_symbol_bars

with LabClient.from_env() as client:
    download_symbol_bars(
        client,
        "archive/1s-14d",
        days=14,
        grain="1s",
        incremental=True,
    )
```

اجرای مجدد فقط روزهای غایب را می‌گیرد.

### ب) API تاریخی

```yaml
data:
  provider: goldarb_api
  source: https://goldarb.ir
  symbols: ["طلا", "عیار"]
  grain: 1s
  start: "2026-09-01"
  end: "2026-09-15"

runtime:
  mode: backtest
```

این حالت `GOLDARB_TOKEN` می‌خواهد.

### ج) داده خیلی کوچک برای دیباگ استراتژی

از `HistoricalDataProvider.from_closes(...)` یا دموی `examples/data/price-momentum-demo/` استفاده کن. برای نوشتن منطق سیگنال این مسیر بهتر از آرشیو ۱۴روزه است.

نکته سشن: پیش‌فرض، داده به ساعت ۱۲:۰۰ تا ۱۷:۰۰ تهران محدود می‌شود. `fill_session: true` هر ثانیه این بازه را روی روزهای دارای داده پر می‌کند و سنگین است. برای تست اول `fill_session: false` بگذار.

---

## ۴. تعریف Strategy

فایل جدید مثلاً:

`src/goldarb/strategies/my_strategy.py`

حداقل قرارداد:

```python
from goldarb.strategy import Strategy, StrategyContext
from goldarb.simulation.models import Side


class MyStrategy(Strategy):
    name = "my_strategy"
    version = "1"

    def __init__(self, *, quantity: str = "1") -> None:
        self.quantity = quantity

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        for quote in snapshot.quotes:
            if quote.last is None:
                continue
            if ctx.held(quote.symbol) <= 0:
                ctx.emit_signal(symbol=quote.symbol, side=Side.BUY)
                ctx.submit_order(
                    symbol=quote.symbol,
                    side="BUY",
                    quantity=self.quantity,
                    order_type="MARKET",
                    client_order_id=f"{self.name}:{snapshot.event_id}:{quote.symbol}:BUY",
                )
```

Hookها:

| متد | کی صدا می‌شود |
| --- | --- |
| `on_start(ctx)` | یک‌بار قبل از تیک‌ها |
| `on_market_data(ctx)` | هر snapshot بازار؛ اجباری |
| `on_fill(ctx, fill)` | بعد از هر Fill جدید |
| `on_stop(ctx)` | پایان اجرا |

از `ctx` می‌توانی این‌ها را بگیری:

- `ctx.market`: snapshot جاری، شامل `quotes`
- `ctx.clock`: زمان همان snapshot
- `ctx.held(symbol)`: مقدار پوزیشن
- `ctx.portfolio()`: cash، equity، PnL
- `ctx.open_orders()`
- `ctx.emit_signal(...)`
- `ctx.submit_order(...)`
- `ctx.cancel_order(order_id)`

هر `quote` معمولاً این فیلدها را دارد:

- `symbol`
- `last`
- `bid` / `ask`
- `premium`
- `nav`

قواعد مهم:

- HTTP نزن.
- فایل آرشیو نخوان.
- SQLite باز نکن.
- Broker را مستقیم صدا نزن.
- تصمیم را روی دادهٔ `ctx.market` بگیر، نه روی حدس از زمان سیستم.

پارامترهای قابل تنظیم را در `__init__` بگیر تا از YAML تزریق شوند:

```yaml
strategy:
  name: my_strategy
  params:
    quantity: "1"
```

سپس:

```python
strategy = MyStrategy(**config.strategy.params)
```

`StrategyRunner` کلاس Strategy را از روی `name` نمی‌سازد. خودت باید کلاس را import و instantiate کنی.

بعد از نوشتن کلاس، آن را در `src/goldarb/strategies/__init__.py` و در صورت نیاز `src/goldarb/__init__.py` export کن.

استراتژی‌های آماده:

| کلاس | ایده |
| --- | --- |
| `BubbleSignStrategy` | حباب منفی → خرید؛ حباب مثبت → فروش |
| `PriceMomentumStrategy` | رشد بیش از آستانه → خرید؛ افت → خروج |
| `MaBandStrategy` | باند میانگین متحرک روی یک نماد |
| `BubbleRankStrategy` | ارزان‌ترین/گران‌ترین صندوق نسبت به میانگین پریمیوم |
| `PairZScoreStrategy` | جفت ثابت با z-score اسپرد پریمیوم |

برای جفت‌ها معمولاً `allow_short: true` لازم است.

---

## ۵. فایل کانفیگ

فرمت‌ها: YAML، JSON، TOML.

نمونه کامل:

```yaml
data:
  provider: archive
  source: archive/1s-14d
  dataset: fund-bars
  symbols: ["طلا", "عیار"]
  grain: 1s
  start: "2026-09-15"
  end: "2026-09-15"
  fill_session: false

runtime:
  mode: offline_backtest
  initial_cash: "1000000000"
  allow_short: false
  database: ":memory:"

session:
  timezone: Asia/Tehran
  start: "12:00:00"
  end: "17:00:00"
  poll_seconds: 1.0

strategy:
  name: my_strategy
  params:
    quantity: "1"

fee:
  name: PercentFee
  params:
    fee_rate: "0.0005"

slippage:
  name: NoSlippage

latency:
  name: NoLatency
```

### `data`

| فیلد | معنی |
| --- | --- |
| `provider` | `archive`، `jsonl`، `parquet`، `goldarb_api` |
| `source` | مسیر پوشه آرشیو یا URL API |
| `symbols` | لیست نمادها |
| `grain` | `1s`، `1m`، `daily` |
| `start` / `end` | فیلتر تاریخ |
| `fill_session` | پر کردن کل ۱۲–۱۷ تهران |
| `session_hours` | محدود کردن به سشن ایران |

`dataset` فعلاً فقط در کانفیگ ذخیره می‌شود و Provider را عوض نمی‌کند.

### `runtime`

| مقدار `mode` | معنی |
| --- | --- |
| `offline_backtest` | آرشیو محلی + LocalSimulator |
| `backtest` | داده تاریخی API + LocalSimulator |
| `live_paper_local` | داده زنده + matching در SDK |
| `live_paper_remote` | داده زنده + matching روی سرور |

سایر فیلدها:

- `initial_cash`
- `allow_short`
- `database`: `:memory:` یا مسیر SQLite
- `account_id`: اگر بخواهی حساب موجود را ادامه بدهی

### مدل‌های اجرا

Fee:

```yaml
fee:
  name: PercentFee
  params:
    fee_rate: "0.0005"
```

یا `NoFee`.

Slippage:

- `NoSlippage`
- `FixedSlippage` با `amount`
- `PercentSlippage` با `fraction`

Latency:

- `NoLatency`
- `FixedLatency` با `milliseconds`

در `live_paper_remote` فقط `NoSlippage` و `NoLatency` مجاز است، چون matching سمت سرور است.

---

## ۶. اجرای بک‌تست

اسکریپت نمونه:

```python
from goldarb import AppConfig, StrategyRunner
from goldarb.strategies.my_strategy import MyStrategy

config = AppConfig.from_file("examples/runtime.my_strategy.yaml")
strategy = MyStrategy(**config.strategy.params)
result = StrategyRunner.from_config(config).run(strategy)

print(result.metrics.n_orders, result.metrics.n_trades, result.portfolio.equity)
```

`StrategyRunner` بر اساس کانفیگ این‌ها را می‌سازد:

- DataProvider
- Engine
- Broker
- Fee / Slippage / Latency

تو فقط Strategy را می‌سازی.

خواندن نتیجه:

```python
result.metrics.total_return
result.metrics.total_pnl
result.metrics.max_drawdown
result.metrics.n_signals
result.metrics.n_orders
result.metrics.n_filled_orders
result.metrics.fill_rate
result.metrics.total_fees

result.portfolio.cash
result.portfolio.equity
result.portfolio.positions

result.orders
result.fills
result.signals
result.equity_history
result.config
```

اگر `database` را فایل بگذاری، سفارش‌ها و equity در SQLite می‌مانند. برای تکرارپذیری تست، `:memory:` ساده‌تر است.

بدون YAML هم می‌شود:

```python
from goldarb import BacktestEngine, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import PercentFee

result = BacktestEngine().run(
    MyStrategy(quantity="1"),
    HistoricalDataProvider.from_closes(("100", "101", "99")),
    RunConfig(strategy_name="my_strategy", initial_cash="10000"),
    fee=PercentFee("0"),
)
```

مسیر کانفیگ برای کار تیمی بهتر است.

---

## ۷. عوض کردن استراتژی بدون عوض کردن موتور

دو چیز را عوض کن:

1. کلاس در اسکریپت اجرا
2. بلوک `strategy` در YAML

موتور، آرشیو و Broker می‌توانند ثابت بمانند.

مثال:

- `examples/run_from_config.py` از `BubbleSignStrategy` استفاده می‌کند.
- `examples/run_price_momentum_from_config.py` از `PriceMomentumStrategy`.

هر دو از `AppConfig` و `StrategyRunner` می‌روند.

---

## ۸. رفتن از بک‌تست به پیپر لایو

Strategy را عوض نکن. کانفیگ را عوض کن:

```yaml
data:
  provider: goldarb_live
  source: https://goldarb.ir
  symbols: ["طلا", "عیار"]
  grain: 1s

runtime:
  mode: live_paper_local
```

`live_paper_remote` سفارش را به شبیه‌ساز سرور می‌فرستد. سفارش واقعی به بازار ارسال نمی‌شود.

---

## ۹. اشتباه‌های رایج

- نصب `goldarb-lab[yaml]` از PyPI به‌جای نصب editable از همین ریپو
- استفاده از Python 3.10؛ پروژه `>=3.11` می‌خواهد
- گذاشتن توکن داخل YAML
- انتظار اینکه `strategy.name` کلاس را خودکار بسازد
- زدن HTTP داخل Strategy
- اجرای کل آرشیو ۱۴روزه با `fill_session: true` برای تست اول
- فراموش کردن `allow_short: true` برای استراتژی جفت
- آرشیو بدون `manifest.json` با `offline_backtest`؛ برای JSONL خام `provider: jsonl` بگذار و `symbols` را صریح بنویس

---

## ۱۰. چک‌لیست قبل از تحویل یک استراتژی جدید

1. کلاس از `Strategy` ارث می‌برد و `on_market_data` دارد.
2. پارامترها از `__init__` می‌آیند و با YAML سازگارند.
3. تست واحد با داده کوچک نوشته شده است.
4. یک YAML نمونه کنار مثال‌ها هست.
5. اسکریپت اجرا فقط Strategy را عوض می‌کند، نه Engine را.
6. بک‌تست آفلاین روی دمو یا یک روز آرشیو سبز است.
