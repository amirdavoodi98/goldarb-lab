# راهنمای استفاده از SDK گلدآرب‌لب

این سند نحوهٔ کار با `goldarb-lab` را برای تیم تریدینگ شرح می‌دهد.
نیازمندی‌ها در [`srs-sdk-v0.1.md`](srs-sdk-v0.1.md) است.
جزئیات مچینگ سفارش در [`local-simulator-fa.md`](local-simulator-fa.md) است.
راهنمای نوشتن Strategy، تنظیم YAML و گرفتن بک‌تست:
[`strategy-backtest-guide-fa.md`](strategy-backtest-guide-fa.md).

یک `Strategy` را یک‌بار می‌نویسید؛ همان کلاس روی بک‌تست تاریخی و پیپر لایو اجرا می‌شود.
موتور داده و کارگزار را جدا از منطق سیگنال نگه می‌دارد.

## نصب و ورود

Python 3.11 یا جدیدتر:

```bash
pip install -e ".[pandas,dev]"
```

متغیرهای محیط:

```bash
export GOLDARB_BASE_URL=https://goldarb.ir
export GOLDARB_TOKEN=your_token_here
```

یا به‌جای توکن: `GOLDARB_USERNAME` و `GOLDARB_PASSWORD`.

```python
from goldarb import LabClient

with LabClient.from_env() as client:
    pass
```

## دریافت داده

```python
from goldarb import GOLD_FUND_SYMBOLS, LabClient

with LabClient.from_env() as client:
    bars = client.fund.candles("طلا", start="2026-07-01", end="2026-07-03", grain="1s")
    many = client.fund.candles_many(GOLD_FUND_SYMBOLS, start="2026-08-01", end="2026-08-29", grain="1s")
    last = client.fund.last_price("طلا")
    navs = client.fund.navs_live()
```

`grain` صندوق: `1s`، `1m`، یا `daily`.
تاریخچهٔ `1s` در API یک روز تقویمی در هر درخواست است؛ SDK بازهٔ بلندتر را تکه می‌کند.

### زمان خوانش قیمت از منبع

در پاسخ `last_price` و برای هر نماد در `last_prices`، فیلد `fetched_at`
زمان خوانش از منبع توسط سرویس جمع‌آوری داده است؛ قالب آن ISO 8601 با منطقهٔ زمانی
است. `last_update` نام قدیمی همین فیلد است. `d_even` و `h_even` زمان معامله‌اند.

زمان منبع جداگانه در `source_timestamp` و وضعیت اعتبار آن در
`source_time_status` ارائه می‌شود؛ هر دو در خروجی تک‌نماد، گروهی و `Quote`
استراتژی موجودند. مقدار ساخته‌شده از فیلدهای قدیمی `d_even`/`h_even` وضعیت
`unverified` دارد؛ زمان ناموجود با زمان خوانش جایگزین نمی‌شود.
جزئیات و مثال‌ها در [راهنمای زمان منبع](source-time-fa.md) است.

در دادهٔ ورودی Strategy، هر `Quote` نیز `fetched_at` را به شکل `datetime` دارای
منطقهٔ زمانی نگه می‌دارد. زمان خوانش دفتر سفارش جداگانه در
`orderbook_fetched_at` موجود است. اگر `last` از میانگین بهترین خرید و فروش ساخته
شود، `fetched_at` آن از دفتر سفارش گرفته می‌شود. این زمان‌ها با تأخیر، تکرار
پولینگ یا ادغام NAV تغییر نمی‌کنند و دقت اعشاری منبع حفظ می‌شود.

`MarketSnapshot.timestamp` در `LiveDataProvider` زمان رویداد پولینگ است؛ برای
سنجش تازگی قیمت از `quote.fetched_at` استفاده کنید. اگر زمان خوانش موجود یا معتبر
نباشد (از جمله زمان بدون منطقهٔ زمانی)، مقدار آن `None` است و با زمان فعلی یا
زمان معامله جایگزین نمی‌شود. این فیلد برای کندل تاریخی نیز فقط در صورت وجود
اطلاعات خوانش منبع پر می‌شود؛ زمان کندل، زمان خوانش نیست.

نمونهٔ تصمیم‌گیری در Strategy با آستانهٔ دلخواه تیم تحلیل:

```python
from datetime import UTC, datetime

max_age_seconds = 3.0
for quote in snapshot.quotes:
    if quote.fetched_at is None:
        continue
    age = (datetime.now(UTC) - quote.fetched_at).total_seconds()
    if not 0 <= age <= max_age_seconds:
        continue
    # تولید سیگنال با quote.last
```

یونیورس جفت‌ها ۳۰ صندوق طلا است: `GOLD_FUND_SYMBOLS`.

### دانلود incremental و آرشیو نسخه‌دار

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

اجرای مجدد فقط روزهای موجودنبودۀ هر نماد را دریافت می‌کند. `manifest.json`
شامل نسخه schema، بازه، source، checksum، تعداد ردیف و گزارش روزهای فاقد داده است.
آرشیوهای JSONL قدیمی همچنان قابل خواندن‌اند. برای Parquet، extra مربوط را نصب و
`format="parquet"` ارسال کنید:

```bash
pip install -e ".[parquet]"
```

## اجرای مبتنی بر کانفیگ

`AppConfig` فایل JSON، TOML و YAML را می‌خواند. برای YAML:

```bash
pip install -e ".[yaml]"
python examples/strategy_runners/run_from_config.py examples/runtime.example.yaml
```

```python
from goldarb import AppConfig, BubbleSignStrategy, StrategyRunner

config = AppConfig.from_file("examples/runtime.example.yaml")
strategy = BubbleSignStrategy(**config.strategy.params)
result = StrategyRunner.from_config(config).run(strategy)
```

حالت‌های معتبر `runtime.mode` عبارت‌اند از `backtest`،
`offline_backtest`، `live_paper_local` و `live_paper_remote`. با تغییر mode و
data provider، کد Strategy تغییر نمی‌کند. providerهای تاریخی `goldarb_api`،
`jsonl`، `parquet` و `archive` هستند. توکن در فایل کانفیگ قرار نمی‌گیرد و از
`GOLDARB_TOKEN` خوانده می‌شود.

## قرارداد Strategy

استراتژی فقط با `StrategyContext` حرف می‌زند: بازار جاری، پورتفوی، ثبت سفارش.
HTTP، SQLite و API را نمی‌بیند.

```python
from goldarb import Strategy, StrategyContext

class MyStrategy(Strategy):
    name = "my_strategy"

    def on_start(self, ctx: StrategyContext) -> None:
        return

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        ctx.submit_order(symbol="طلا", side="BUY", quantity="1")
```

`BacktestEngine` و `LiveSimulationEngine` هر دو همین هوک‌ها را صدا می‌زنند.
قبل از مچینگ، مدل کارمزد / اسلیپیج / تأخیر اعمال می‌شود و سفارش‌ها به `LocalSimulator` می‌روند.

## مسیر اصلی: بک‌تست ماه، سپس سشن لایو ایران

مهم‌ترین مسیر آزمایش استراتژی جفت:

1. بک‌تست روی حدود ۳۰ روز کندل `grain=1s` سشن نقدی ایران.
2. همان نمونهٔ استراتژی را در سشن امروز ۱۲:۰۰–۱۸:۰۰ تهران (شنبه تا چهارشنبه)، با پول هر **یک ثانیه**، پیپر کنید.

```python
from goldarb import BubbleRankStrategy, LabClient, iran_session_live, month_backtest

strategy = BubbleRankStrategy(capital_per_side="100000000", min_samples=10, min_gap=1.0)
with LabClient.from_env() as client:
    month = month_backtest(
        strategy, client, days=30, grain="1s", fill_session=True, allow_short=True
    )
    live = iran_session_live(
        strategy,
        client,
        poll_seconds=1.0,
        lookback_days=0,
        include_session_bars=False,
        allow_short=True,
    )
```

همان `strategy` را نگه دارید تا پنجرهٔ تقویمی پریمیوم گرم بماند.
`on_start` پوزیشن منطقی جفت را صفر می‌کند ولی تاریخچه را پاک نمی‌کند مگر `reset_history` در کانفیگ ران `true` باشد.

بعد از بک‌تست ماهانه حتماً `lookback_days=0` و `include_session_bars=False` بگذارید تا لایو همان تاریخچه را دوباره روی حساب جدید معامله نکند.

اگر فقط لایو را بدون بک‌تست ماهانه می‌زنید، برای گرم‌کردن پنجره از `lookback_days=20` استفاده کنید.

استراتژی جفت نیاز به `allow_short=True` صریح دارد. پایپلاین‌ها دیگر آن را پنهان `true` نمی‌گذارند. پریمیوم روی کوت لازم است (`premium` یا close+NAV).

خروجی هر دو تابع `RunResult` است: سفارش، فیل، پورتفوی، متریک، لاگ.

```python
print(month.metrics.n_filled_orders, month.metrics.total_return, month.portfolio.equity)
print([item.get("type") for item in strategy.events])
```

### پوشش یک ثانیه

SDK باید بتواند **هر ثانیه** را پوشش دهد:

| مسیر | رفتار |
| --- | --- |
| `month_backtest(..., grain="1s", fill_session=True)` | روی هر روز معاملاتی (شنبه تا چهارشنبه) که داده دارد، از ۱۲:۰۰ تا ۱۸:۰۰ تهران هر ثانیه یک اسنپ‌شات (حدود ۲۱۶۰۱ نقطه در روز سشن). شب و پنج‌شنبه/جمعه پر نمی‌شود. |
| `month_backtest(..., fill_session=False)` | فقط ثانیه‌های بین اولین و آخرین بار همان روز سشن، با ffill. |
| `iran_session_live(..., poll_seconds=1.0)` | پول زنده هر ۱٫۰ ثانیه تا ۱۸:۰۰ در روزهای شنبه تا چهارشنبه. پیش‌فرض `LiveDataProvider` هم `poll_seconds=1.0` و `bar_grain="1s"` است. |

`window_days` تعداد تیک نیست؛ پنجرهٔ **تقویمی** روی پریمیوم‌های زمان‌دار ۱ ثانیه‌ای است.

`fill_session=True` روی ماه کامل سنگین است (۳۰ نماد × حدود ۲۰ روز سشن × ۲۱۶۰۱ ثانیه). برای آزمایش محلی `GOLDARB_FILL_SESSION=0` روی مثال ماهانه.

## استراتژی‌های آماده

| کلاس | کار |
| --- | --- |
| `BubbleRankStrategy` | در هر ثانیه ارزان‌ترین / گران‌ترین صندوق نسبت به میانگین پریمیوم خودش؛ ورود جفت اگر فاصله از `min_gap` بیشتر باشد. پیش‌فرض `window_days=20`. |
| `PairZScoreStrategy` | جفت ثابت (پیش‌فرض طلا / زر) وقتی قدرمطلق z اسپرد پریمیوم از آستانه بگذرد. پیش‌فرض `window_days=90`؛ برای بک‌تست ۳۰ روزه `window_days=min(90, days)` بگذارید. |
| `MaBandStrategy` | باند میانگین متحرک روی یک نماد (نمونهٔ غیرجفت). |

ورود جفت فقط وقتی **هر دو پا** `FILLED` شوند؛ در غیر این صورت رول‌بک می‌شود.

## موتورها بدون پایپلاین

برای کنترل دستی داده:

```python
from goldarb import BacktestEngine, BubbleRankStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import PercentFee

result = BacktestEngine().run(
    BubbleRankStrategy(capital_per_side="100000"),
    HistoricalDataProvider.from_1s(
        12,
        premiums={"طلا": [0] * 11 + [-2.5], "زر": [0] * 11 + [2.5]},
    ),
    RunConfig(strategy_name="bubble_rank", initial_cash="1000000", allow_short=True),
    fee=PercentFee("0"),
)
```

کندل واقعی API:

```python
from datetime import date, timedelta

from goldarb import GOLD_FUND_SYMBOLS, LabClient
from goldarb.data import HistoricalDataProvider

with LabClient.from_env() as client:
    last = date.today()
    first = last - timedelta(days=30)
    provider = HistoricalDataProvider.from_symbol_bars(
        client.fund.candles_many(
            GOLD_FUND_SYMBOLS, start=first, end=last, grain="1s"
        ),
        session_hours=True,
        fill_session=True,
        lazy=True,
    )
```

`session_hours=True` (پیش‌فرض) گرید را به ۱۲:۰۰–۱۷:۰۰ تهران محدود می‌کند.

## مثال‌های اجرایی

```bash
python examples/backtesting/backtest_month_1s.py
python examples/simulation/simulate_iran_session_1s.py
python examples/backtesting/backtest_bubble_rank.py
python examples/backtesting/backtest_pair_zscore.py
python examples/backtesting/backtest_ma_band.py
```

`simulate_iran_session_1s.py` تا ۱۲:۰۰ تهران صبر می‌کند و تا ۱۸:۰۰ هر ثانیه پول می‌کند.
اگر سشن همان روز بسته شده باشد خارج می‌شود.

## محدودیت‌ها

- `candles_many` حلقهٔ کلاینت روی endpoint تک‌نمادی است؛ bulk سروری هنوز نیست.
- شبیه‌ساز عمق فقط بهترین bid/ask همان سطح را می‌بیند.
- حساب پیپر لایو پیش‌فرض جدا از حساب بک‌تست ماهانه است (هر ران `LocalSimulator` تازه، مگر خودتان همان فایل را پاس دهید).
- تست‌های CI آفلاین‌اند و به API زنده وصل نمی‌شوند.


## تازه‌ترین معامله بین سه منبع

```python
price = client.fund.latest_price("طلا")
prices = client.fund.latest_prices()
if price["status"] == "ok":
    print(price["last_price"], price["source"], price["source_timestamp"])
```

این مسیر بین آگاه، مفید و TSETMC بر اساس زمان تأییدشدهٔ آخرین معامله
انتخاب می‌کند؛ زمان دریافت معیار انتخاب نیست. واحد قیمت ریال است.
`fetched_at`/`received_at` زمان دریافت و `source_timestamp` زمان معامله است.
در تساوی زمان، اولویت ثابت TSETMC، مفید، آگاه اعمال می‌شود.
`age_seconds` سن معامله است؛ آستانهٔ پیش‌فرض سه ثانیه است.
اگر معامله قدیمی باشد `stale` و اگر داده معتبر موجود نباشد `unavailable`
برمی‌گردد. قیمت پایانی یا میانگین سفارش‌ها جایگزین آخرین معامله نمی‌شود.

مسیر اجرای زندهٔ استراتژی از طریق `LabLiveFeed` به‌صورت پیش‌فرض از این API
استفاده می‌کند و ردیف‌های `stale`/`unavailable` را وارد snapshot نمی‌کند.
توابع قدیمی `fund.last_price()` و `fund.last_prices()` همچنان فقط TSETMC هستند.
برای انتخاب صریح مسیر قدیمی: `LabLiveFeed(client, price_policy="tsetmc")`.

ابتدا بک‌اند و گردآورنده‌های نسخهٔ جدید را مستقر کنید، سپس SDK را به‌روز کنید.
stream باید فعال باشد و قرارداد زمان هر منبع قبل از فعال‌سازی تنظیم تأیید زمان
آن منبع بررسی شود. تنظیم‌های تأیید زمان به‌صورت پیش‌فرض خاموش‌اند؛ بدون آن‌ها
خروجی ناموجود طبیعی است. خطای API جدید به مسیر قدیمی تبدیل نمی‌شود.
