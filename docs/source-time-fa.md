# دریافت قیمت و زمان مرجع با SDK اصلی

مسیر اصلی این SDK، مخزن مستقل goldarb-lab است. قابلیت‌های دریافت زندهٔ
پلتفرم در نسخهٔ 0.9.0 با APIهای موجود استراتژی، آرشیو و شبیه‌سازی یکپارچه‌اند.

## راه‌اندازی

از ریشهٔ پروژه و در محیط مجازی خودتان:

```bash
pip install -e ".[pandas,dev]"
```

نشانی پلتفرم و توکن حساب خود را در `GOLDARB_BASE_URL` و `GOLDARB_TOKEN`
قرار دهید. `LabClient.from_env()` این دو مقدار را از محیط فرایند می‌خواند.
برای دریافت توکن با نام کاربری و رمز، `LabClient.login()` نیز موجود است.
رمز و توکن را در کد، خروجی مثال‌ها یا مخزن قرار ندهید.

## آخرین قیمت یک صندوق

دو زمان مستقل موردنیاز در رابط `client.live` از قبل وجود دارند:

| مفهوم | فیلد |
| --- | --- |
| زمان خود داده که منبع اعلام کرده است | `source_timestamp` |
| زمان دریافت داده توسط collector | `received_at` |
| زمان معامله، فقط در صورت تأیید معنای ساعت منبع | `source_event_time` |
| وضعیت اعتبار زمان منبع | `source_time_status` |

مثلاً داده‌ای با زمان منبع `09:05:00` که در `09:05:35` دریافت شده، دو
مقدار متفاوت در `source_timestamp` و `received_at` دارد؛ زمان دریافت نباید
جایگزین زمان منبع شود. `received_at` زمان دریافت است، نه لزوماً لحظهٔ commit
دیتابیس. در رابط قدیمی `fund.last_price`، `fetched_at` نیز زمان خوانش است و
`last_update` نام قدیمی همان زمان است؛ هیچ‌کدام زمان به‌روزرسانی منبع نیستند.

برای کندل، `bar_at` زمان بازهٔ کندل است، نه زمان انتشار آخرین اصلاح کندل از
طرف منبع. این سه مفهوم را با یکدیگر یکی نگیرید.

### همین اطلاعات در `client.fund`

متدهای `client.fund.last_price(symbol)` و `client.fund.last_prices()` نیز اکنون
`source_timestamp` و `source_time_status` را کنار `fetched_at` برمی‌گردانند.
این کار درخواست شبکهٔ اضافی ندارد و قیمت را با snapshot دیگری ادغام نمی‌کند.

```python
with LabClient.from_env() as client:
    price = client.fund.last_price("طلا")
    print("زمان منبع:", price["source_timestamp"])
    print("زمان خوانش:", price["fetched_at"])
    print("اعتبار زمان منبع:", price["source_time_status"])
```

اگر پاسخ سرور `source_timestamp` داشته باشد، همان مقدار و وضعیت آن استفاده
می‌شود. برای پاسخ قدیمی فاقد این فیلد، ترکیب معتبر و کامل `d_even`/`h_even`
به زمان دارای منطقهٔ زمانی `Asia/Tehran` تبدیل می‌شود، با وضعیت `unverified`.
برخی بک‌اندهای قدیمی تاریخ `d_even` را هنگام نبودن تاریخ منبع استنتاج می‌کنند؛
بنابراین این ترکیب هرگز به‌عنوان زمان تأییدشده معرفی نمی‌شود. برای سیاست سختگیرانه،
علاوه بر موجود بودن زمان، وضعیت اعتبار ارائه‌شده توسط منبع را بررسی کنید.

تاریخ یا ساعت ناقص، زمان بدون timezone و مقدار نامعتبر، `None` می‌شوند.
زمان `fetched_at` یا زمان فعلی جای تاریخ ناموجود قرار نمی‌گیرد. اگر سرور
صریحاً `source_timestamp=None` داده باشد، SDK آن را با فیلدهای قدیمی پر نمی‌کند.

در مسیر معمول استراتژی نیز `quote.source_timestamp` (به شکل `datetime` دارای
timezone) و `quote.source_time_status` کنار `quote.fetched_at` حفظ می‌شوند؛
پولینگ تکراری، ادغام NAV و forward fill زمان منبع را عوض نمی‌کنند. اگر قیمت
از midpoint دفتر سفارش ساخته شود، زمان منبع فقط از همان دفتر سفارش می‌آید؛
اگر دفتر زمان منبع نداشته باشد، `None` خواهد بود.

نمونهٔ آفلاین و حالت دریافت از سرور:

```bash
python examples/price_timestamps/fund_source_timestamp.py
python examples/price_timestamps/fund_source_timestamp.py --live
```

### مسیر `client.live`

```python
from goldarb import LabClient

with LabClient.from_env() as client:
    snapshot = client.live.snapshot(
        source="mofid",
        symbols=["گلدیس"],
        require_verified_source_time=False,
    )
    for price in snapshot["observations"]:
        print(price["symbol"], price["payload"]["last_price"])
        print("زمان اعلامی مرجع:", price["source_timestamp"])
        print("وضعیت اعتبار زمان:", price["source_time_status"])
        print("زمان دریافت collector:", price["received_at"])
```

قیمت با واحد مشخص‌شده در `price_unit` برمی‌گردد؛ مشاهدات فعلی صندوق‌ها ریالی
هستند. زمان‌ها ISO 8601 و همراه timezone هستند. ساعت خام مرجع و نام فیلد آن
در `source_time_raw` و `source_time_field` حفظ می‌شوند.

`source_timestamp` حتی برای زمان تأییدنشده در دسترس است، اگر مرجع تاریخ و
ساعت قابل‌خواندن داده باشد. `source_event_time` فقط برای زمان معاملهٔ
تأییدشده پر می‌شود. حالت پیش‌فرض strict دادهٔ تأییدنشده را فیلتر می‌کند؛
گزینهٔ False در مثال بالا انتخاب صریح برای دریافت آن داده‌هاست.

برای TSETMC از `source="tsetmc"` استفاده کنید. پاسخ MarketWatch مشاهده‌شده
فعلاً `dEven=0` و ساعت خام دارد؛ timestamp کامل آن خالی می‌ماند. تاریخ
دریافت یا زمان مفید جای تاریخ ناموجود TSETMC قرار نمی‌گیرد.

## دنبال‌کردن تغییرات

```python
with LabClient.from_env() as client:
    snapshot = client.live.snapshot(
        source="mofid", symbols=["گلدیس"], require_verified_source_time=False,
    )
    checkpoint = snapshot["cursor"]
    for batch in client.live.subscribe(
        source="mofid", symbols=["گلدیس"], cursor=checkpoint,
        require_verified_source_time=False,
    ):
        for item in batch["events"]:
            price = item["event"]
            print(price["symbol"], price["payload"], price["source_timestamp"])
        # در برنامهٔ واقعی، ابتدا کل batch را پردازش و ذخیره کنید.
        checkpoint = batch["cursor"]
```

checkpoint را پس از موفقیت پردازش کل batch در ذخیره‌سازی برنامه نگه دارید.
batch خالی هم ممکن است cursor را جلو ببرد. با خطای شبکه، cursor ذخیره‌شده را
حفظ کنید. HTTP 409 یعنی شکاف تاریخچه؛ snapshot جدید را آگاهانه بگیرید. این
روش long-poll است؛ تضمین ثبت همهٔ معاملات بورس یا اجرای سفارش نمی‌دهد.
وضعیت منبع و تازگی دریافت را در `provider_status` و `received_at` بررسی کنید.

## اندازه‌گیری از شبکهٔ تیم استراتژی

```bash
python examples/inspect_source_time.py --source mofid
python examples/probe_live_delivery.py --source mofid --symbols عیار گلدیس --duration 60
```

ابزار دوم فقط API پلتفرم را می‌خواند. تأخیر دریافت تا SDK را از عمر زمانِ
کاندید مرجع جدا گزارش می‌کند؛ عمر کاندید، تأخیر تأییدشدهٔ بورس نیست. تست‌های
خودکار مخزن از پاسخ‌های mock استفاده می‌کنند و به production متصل نمی‌شوند.

## منبع آگاه

متدهای `live.snapshot`، `live.events` و `live.subscribe` مقدار `source="agah"`
را می‌پذیرند. توکن احراز هویت همان توکن پلتفرم است؛ مجوز آگاه روی سرور می‌ماند.
زمان مرجع تا تأیید قرارداد زنده unverified است؛ برای بررسی اولیه فقط با انتخاب
صریح `require_verified_source_time=False` قابل دریافت است. قطع اتصال upstream
ممکن است شکاف ایجاد کند و NATS Core تضمین replay معاملات ندارد.
