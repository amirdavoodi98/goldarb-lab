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
