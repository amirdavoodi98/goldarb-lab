# راهنمای استفاده از LocalSimulator

برای اجرای یک `Strategy` با `BacktestEngine` / `LiveSimulationEngine` و مسیر ماهانهٔ ۱ ثانیه‌ای، سند استفادهٔ SDK را ببینید: [`sdk-usage-fa.md`](sdk-usage-fa.md).

`LocalSimulator` یک paper broker مستقل از استراتژی است. کد استراتژی، زمان شبیه‌سازی
و داده بازار را شما تأمین می‌کنید؛ شبیه‌ساز سفارش‌ها، پرشدن، کارمزد، موجودی نقد،
پوزیشن و سود و زیان را محاسبه و در SQLite ذخیره می‌کند.

این مسیر کاملاً آفلاین است و هیچ درخواست HTTP یا fallback شبکه‌ای ندارد.

## نصب

Python 3.11 یا جدیدتر لازم است:

```bash
pip install -e ./goldarb-lab
```

کلاس‌های موردنیاز:

```python
from goldarb.simulation import (
    LocalSimulator,
    MarketSnapshot,
    OrderStatus,
    OrderType,
    Quote,
    Side,
    get_broker,
)
```

## مدل اجرایی

چرخه معمول استفاده:

1. یک فایل SQLite و account ایجاد یا باز کنید.
2. snapshot بازار را با `feed()` تزریق کنید.
3. استراتژی خود را خارج از simulator اجرا کنید.
4. با `broker.submit_buy()` یا `broker.submit_sell()` سفارش MARKET یا LIMIT ثبت کنید.
5. با هر snapshot جدید دوباره `feed()` را فراخوانی کنید.
6. سفارش‌ها، fillها و portfolio را بخوانید.

`feed()` همه accountهای فعال همان فایل SQLite را بررسی می‌کند. سفارش LIMIT باز،
با snapshotهای بعدی نیز ارزیابی می‌شود؛ بنابراین لازم نیست strategy داخل simulator
پیاده‌سازی شود.

## شروع سریع

```python
from datetime import UTC, datetime
from decimal import Decimal

from goldarb.simulation import LocalSimulator, MarketSnapshot, Quote, get_broker

database = "paper-simulation.sqlite3"
broker = get_broker("agah")

with LocalSimulator(database, broker=broker) as simulator:
    account = simulator.create_account(
        initial_cash="1000000000",
        label="my-local-strategy",
    )

    simulator.feed(
        MarketSnapshot(
            event_id="tala-2026-08-29T09:00:00Z",
            timestamp=datetime(2026, 8, 29, 9, 0, tzinfo=UTC),
            quotes=(
                Quote(
                    symbol="طلا",
                    bid=Decimal("249900"),
                    ask=Decimal("250000"),
                    last=Decimal("249950"),
                    bid_size=Decimal("500"),
                    ask_size=Decimal("600"),
                ),
            ),
        )
    )

    order = broker.submit_buy(
        account,
        symbol="طلا",
        quantity="100",
        order_type="MARKET",
        client_order_id="strategy-a-buy-0001",
    )

    print(order.status)
    print(broker.get_cash(account))
    print(broker.list_holdings(account))
    print(broker.list_orders(account))
    print(simulator.portfolio(account.id))
```

نسخهٔ اول آگاه (`agah`) و مفید (`mofid`) هر دو با `fee_rate="0.0005"` و
`allow_short=False` تطبیق کاغذی می‌کنند. کارمزد و مجوز short از همان آبجکت
کارگزار می‌آید. اگر کنار کارگزار `fee_rate` صریح بدهید، همان نرخ برای آن حساب
استفاده می‌شود.

برای ورودی‌های مالی استفاده از string یا `Decimal` توصیه می‌شود؛ از float برای
قیمت، حجم، سرمایه و کارمزد استفاده نکنید.

## ساخت account

```python
account = simulator.create_account(
    initial_cash="500000000",
    fee_rate="0.001",
    allow_short=True,
    label="pair-trading",
)
```

پارامترها:

- `initial_cash`: سرمایه اولیه؛ باید مثبت باشد.
- `broker`: کارگزار مقصد. اگر ندهید، کارگزار `LocalSimulator(..., broker=...)` روی حساب ذخیره می‌شود (`broker_code`).
- `fee_rate`: نرخ کارمزد اعشاری بین صفر و یک؛ `0.001` یعنی ۰.۱ درصد. اگر خالی باشد از کارگزار می‌آید و اگر صریح باشد همان مقدار برای حساب است.
- `allow_short`: اگر داده شود همان مقدار ذخیره می‌شود؛ اگر خالی باشد از کارگزار می‌آید. آگاه و مفید در نسخهٔ اول short را مجاز نمی‌کنند.
- `label`: نام اختیاری account، حداکثر ۱۲۰ کاراکتر.
- `account_id`: شناسه اختیاری؛ در حالت عادی UUID خودکار مناسب است.

شناسه account را نگه دارید. برای بازکردن دوباره همان account:

```python
with LocalSimulator("paper-simulation.sqlite3", broker=get_broker("agah")) as simulator:
    account = simulator.get_account(saved_account_id)
```

فراخوانی مجدد `create_account()` یک account جدید می‌سازد، حتی اگر همان فایل
SQLite را باز کرده باشید.

## تزریق داده بازار

هر `MarketSnapshot` می‌تواند quote چند نماد را هم‌زمان حمل کند:

```python
snapshot = MarketSnapshot(
    event_id="market-2026-08-29T09:01:00Z",
    timestamp=datetime(2026, 8, 29, 9, 1, tzinfo=UTC),
    quotes=(
        Quote(
            symbol="طلا",
            bid=Decimal("249900"),
            ask=Decimal("250000"),
            bid_size=Decimal("500"),
            ask_size=Decimal("600"),
        ),
        Quote(
            symbol="عیار",
            bid=Decimal("312000"),
            ask=Decimal("312100"),
            bid_size=Decimal("300"),
            ask_size=Decimal("450"),
        ),
    ),
)

accepted = simulator.feed(snapshot)
```

قواعد snapshot:

- `event_id` باید غیرخالی و برای هر رویداد بازار یکتا باشد.
- تزریق دوباره همان `event_id` هیچ اثر جدیدی ندارد و `feed()` مقدار `False` می‌دهد.
- `timestamp` باید timezone-aware باشد.
- timestampها نباید نسبت به snapshot قبلی عقب بروند.
- `bid` قیمت اجرای SELL و `ask` قیمت اجرای BUY است.
- اگر bid یا ask مربوط به سمت سفارش موجود نباشد، `last` به‌عنوان fallback استفاده می‌شود.
- `bid_size` و `ask_size` ظرفیت قابل‌پرشدن همان رویداد هستند.
- اگر size برابر `None` باشد، محدودیت عمق برای آن quote اعمال نمی‌شود.
- چند سفارش یک account در یک event عمق مشترک دارند و نمی‌توانند حجم یکسان را چندبار مصرف کنند.

### تبدیل bar به snapshot

برای داده OHLCV که orderbook ندارد، می‌توانید قیمت close را به `last` تزریق کنید:

```python
snapshot = MarketSnapshot(
    event_id=f"bar:{bar_timestamp.isoformat()}",
    timestamp=bar_timestamp,
    quotes=(
        Quote(
            symbol="طلا",
            last=Decimal(str(bar["close"])),
        ),
    ),
)
```

در این حالت spread و عمق واقعی شبیه‌سازی نمی‌شود. برای مدل واقع‌گرایانه‌تر،
bid/ask و حجم دو سمت را تزریق کنید.

## سفارش MARKET

```python
order = broker.submit_buy(
    account,
    symbol="طلا",
    quantity="100",
    order_type=OrderType.MARKET,
    client_order_id="buy-0001",
)
```

اگر آخرین quote موجود باشد، سفارش هنگام ثبت فوراً match می‌شود. اگر هنوز هیچ
snapshotی وجود نداشته باشد، سفارش باز می‌ماند تا اولین `feed()` حاوی همان نماد.

باقی‌مانده سفارش MARKET پس از ارزیابی همان snapshot لغو می‌شود. دلایل رایج:

- عمق ناکافی؛ بخش قابل‌پرشدن fill و باقی‌مانده `CANCELLED` می‌شود.
- نقدینگی ناکافی؛ حجم خرید ممکن است تا مقدار قابل‌پرداخت کاهش یابد.
- فروش در account بدون short و بدون پوزیشن؛ سفارش `REJECTED` می‌شود.
- نبود قیمت معتبر در quote؛ سفارش `REJECTED` می‌شود.

## سفارش LIMIT

```python
order = broker.submit_buy(
    account,
    symbol="طلا",
    quantity="100",
    order_type="LIMIT",
    limit_price="248000",
    client_order_id="limit-buy-0001",
)
```

شرط crossing:

- BUY LIMIT زمانی قابل اجرا است که `ask <= limit_price`.
- SELL LIMIT زمانی قابل اجرا است که `bid >= limit_price`.

اگر قیمت مناسب نباشد، سفارش `OPEN` می‌ماند. اگر فقط بخشی از حجم قابل اجرا باشد،
وضعیت `PARTIALLY_FILLED` می‌شود و باقی‌مانده با snapshotهای بعدی ادامه پیدا می‌کند.

لغو سفارش باز:

```python
cancelled = broker.cancel_order(order)
```

## وضعیت سفارش‌ها

- `OPEN`: هنوز fill نشده و منتظر snapshot مناسب است.
- `PARTIALLY_FILLED`: بخشی پر شده و باقی‌مانده باز است.
- `FILLED`: کل حجم سفارش پر شده است.
- `CANCELLED`: کاربر یا قواعد MARKET باقی‌مانده را لغو کرده‌اند.
- `REJECTED`: یک قانون دامنه مانند ممنوعیت short یا نبود قدرت خرید مانع اجرا شده است.

خواندن سفارش‌ها و fillها:

```python
order = simulator.get_order(account.id, order_id)
orders = broker.list_orders(account)
fills = simulator.list_fills(account.id)

for fill in fills:
    print(fill.quantity, fill.price, fill.fee, fill.market_event_id)
```

## idempotency سفارش

برای هر تصمیم strategy یک `client_order_id` پایدار و یکتا تعیین کنید:

```python
client_order_id = f"my-strategy:{signal_timestamp.isoformat()}:طلا:BUY"
```

ارسال دوباره همان شناسه در همان account، سفارش موجود را برمی‌گرداند و سفارش
جدیدی ایجاد نمی‌کند. یک `client_order_id` را برای payload متفاوت دوباره استفاده
نکنید.

## Portfolio و سود و زیان

```python
portfolio = simulator.portfolio(account.id)
holdings = broker.list_holdings(account)
cash = broker.get_cash(account)

print("cash:", cash)
print("equity:", portfolio.equity)
print("fees:", portfolio.fees_paid)
print("realized:", portfolio.realized_pnl)
print("unrealized:", portfolio.unrealized_pnl)

for position in portfolio.positions:
    print(
        position.symbol,
        position.quantity,
        position.average_cost,
        position.mark_price,
        position.market_value,
    )
```

تعاریف:

- `cash`: وجه نقد باقی‌مانده پس از notional و کارمزد.
- `market_value`: مقدار پوزیشن ضربدر قیمت mark.
- `equity`: وجه نقد به‌علاوه ارزش بازار همه پوزیشن‌ها.
- `average_cost`: میانگین موزون بهای پوزیشن باز.
- `realized_pnl`: سود یا زیان ناشی از بستن حجم؛ کارمزد جداگانه در `fees_paid` گزارش می‌شود.
- `unrealized_pnl`: سود یا زیان پوزیشن باز بر اساس آخرین mark.
- mark در صورت وجود هر دو سمت، midpoint یعنی `(bid + ask) / 2` است؛ در غیر این
  صورت `last` استفاده می‌شود.

تاریخچه equity:

```python
for point in simulator.equity_history(account.id):
    print(point["recorded_at"], point["equity"])
```

مقادیر تاریخچه مستقیماً از SQLite خوانده می‌شوند و به‌شکل string برمی‌گردند.

## نمونه حلقه strategy

```python
from decimal import Decimal

from goldarb.simulation import LocalSimulator, get_broker


def strategy_signal(close: Decimal, moving_average: Decimal) -> str | None:
    if close < moving_average * Decimal("0.98"):
        return "BUY"
    if close > moving_average * Decimal("1.02"):
        return "SELL"
    return None


broker = get_broker("agah")
with LocalSimulator("strategy.sqlite3", broker=broker) as simulator:
    try:
        account = simulator.get_account(saved_account_id)
    except KeyError:
        account = simulator.create_account(
            initial_cash="1000000000",
            label="ma strategy",
        )
        saved_account_id = account.id

    for snapshot, close, moving_average in data_stream:
        simulator.feed(snapshot)
        side = strategy_signal(close, moving_average)
        if side is None:
            continue
        client_order_id = f"ma-v1:{snapshot.event_id}:طلا:{side}"
        if side == "BUY":
            broker.submit_buy(
                account,
                symbol="طلا",
                quantity="10",
                client_order_id=client_order_id,
            )
        else:
            broker.submit_sell(
                account,
                symbol="طلا",
                quantity="10",
                client_order_id=client_order_id,
            )

    final_portfolio = simulator.portfolio(account.id)
```

## Short position

برای فعال‌کردن short:

```python
account = simulator.create_account(
    initial_cash="1000000000",
    allow_short=True,
)
```

فروش بیشتر از موجودی، quantity پوزیشن را منفی می‌کند. خرید بعدی ابتدا پوزیشن
short را می‌بندد و P&L محقق‌شده را ثبت می‌کند. این مدل margin، leverage، هزینه
borrow یا liquidation ندارد.

## ماندگاری و restart

تمام state مهم داخل فایل SQLite ذخیره می‌شود:

- accountها، وجه نقد و `broker_code`
- سفارش‌ها، کارگزار مقصد (`broker_code`) و fillها
- پوزیشن و بهای تمام‌شده
- آخرین quote هر نماد
- eventهای پردازش‌شده
- تاریخچه equity

برای ادامه اجرا، همان مسیر فایل و `account_id` قبلی را استفاده کنید:

```python
with LocalSimulator("paper-simulation.sqlite3", broker=get_broker("agah")) as simulator:
    account = simulator.get_account(saved_account_id)
    open_orders = [
        order
        for order in simulator.list_orders(account.id)
        if order.status in {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}
    ]
```

از فایل SQLite مانند سایر داده‌های آزمایش نسخه پشتیبان بگیرید. حذف فایل به معنی
حذف کامل state شبیه‌سازی است.

## مدیریت خطا

خطاهای ورودی با `ValueError` گزارش می‌شوند، از جمله:

- سرمایه، حجم یا limit price نامعتبر
- fee rate خارج از بازه
- timestamp بدون timezone یا عقب‌تر از event قبلی
- side یا order type ناشناخته

شناسه account یا order ناشناخته با `KeyError` گزارش می‌شود.

```python
try:
    broker.submit_buy(account, symbol="طلا", quantity="0")
except ValueError as exc:
    print("invalid order:", exc)
```

## محدودیت‌های نسخه ۰.۴

- فقط MARKET و LIMIT پشتیبانی می‌شوند.
- STOP، STOP_LIMIT، margin، leverage و liquidation وجود ندارند.
- simulator داده بازار دانلود نمی‌کند.
- strategy داخل simulator اجرا یا ذخیره نمی‌شود.
- state لوکال با سرور sync نمی‌شود.
- مدل عمق فقط از بهترین bid/ask و حجم همان سطح استفاده می‌کند.
- چند process نویسنده روی یک فایل توصیه نمی‌شود؛ برای هر اجرای مستقل یک فایل
  SQLite جدا انتخاب کنید.
