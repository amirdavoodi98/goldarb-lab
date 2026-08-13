# راهنمای داده‌های تولیدشده در `goldarb-lab`

این سند توضیح می‌دهد هر فایل خروجی چه داده‌ای را نگه می‌دارد، فیلدهای مهم آن چیست، و چگونه می‌توان از آن استفاده کرد.

## 1) `archive/fund_bars_1m/*.jsonl`

این فایل‌ها داده‌های یک‌دقیقه‌ای صندوق‌ها را نگه می‌دارند.  
برای هر صندوق یک فایل جدا وجود دارد، مثل:

- `طلا.jsonl`
- `عیار.jsonl`
- `کهربا.jsonl`
- `مثقال.jsonl`
- `آتش.jsonl`

### نمونه رکورد

```json
{
  "captured_at": "2026-08-09T12:43:01.294322+00:00",
  "symbol": "طلا",
  "bar_at": "2026-08-08T08:30:00+00:00",
  "open": 1320000.0,
  "high": 1320000.0,
  "low": 1311880.0,
  "close": 1319001.0,
  "volume": 408380,
  "nav_price": 1326837.0,
  "premium_discount_pct": -0.5906
}
```

### فیلدها

- `captured_at`: زمان ذخیره شدن رکورد در آرشیو
- `symbol`: نماد صندوق
- `bar_at`: زمان همان کندل دقیقه‌ای
- `open`: قیمت باز شدن
- `high`: بیشترین قیمت
- `low`: کمترین قیمت
- `close`: قیمت بسته شدن
- `volume`: حجم معامله
- `nav_price`: NAV همان لحظه، اگر موجود باشد
- `premium_discount_pct`: درصد premium یا discount نسبت به NAV

### کاربرد

- بک‌تست دقیقه‌ای
- بررسی شکاف داده
- تحلیل premium و رفتار صندوق

### نحوه استفاده

```python
import json

with open("archive/fund_bars_1m/طلا.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

latest = rows[-1]
print(latest["bar_at"], latest["close"])
```

---

## 2) `archive/holdings_history.jsonl`

این فایل تاریخچه snapshot ترکیب دارایی صندوق‌ها را نگه می‌دارد.

### نمونه رکورد

```json
{
  "captured_at": "2026-08-09T11:53:20.021586+00:00",
  "symbol": "عیار",
  "payload": {
    "symbol": "عیار",
    "ins_code": "34144395039913458",
    "status": "ok",
    "as_of": "2026-07-22",
    "age_days": 18,
    "stale_after_days": 45,
    "fetched_at": "2026-07-27T12:38:29.762210+00:00",
    "source": "codal_monthly_portfolio",
    "quality": "official",
    "legs": [...]
  }
}
```

### فیلدهای سطح بالا

- `captured_at`: زمان ذخیره snapshot
- `symbol`: نماد صندوق
- `payload`: کل داده‌ی holdings

### فیلدهای مهم داخل `payload`

- `symbol`: نماد صندوق
- `ins_code`: کد instrument صندوق
- `status`: وضعیت رکورد، مثل `ok`
- `as_of`: تاریخ مرجع پورتفوی
- `age_days`: چند روز از تاریخ مرجع گذشته
- `stale_after_days`: بعد از چند روز داده stale می‌شود
- `fetched_at`: زمان دریافت از منبع
- `source`: منبع داده
- `quality`: کیفیت داده، مثل `official`
- `legs`: لیست دارایی‌های صندوق

### داخل `legs`

هر leg معمولاً شامل این فیلدهاست:

- `leg_type`: نوع دارایی، مثل `gold_bar_cert` یا `gold_coin_cert`
- `quantity`: مقدار دارایی
- `weight_pct`: درصد وزن در NAV
- `raw_label_fa`: عنوان فارسی دارایی

### کاربرد

- بررسی composition صندوق
- تحلیل point-in-time
- استفاده در محاسبه NAV حسابداری

### نحوه استفاده

```python
import json

with open("archive/holdings_history.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

gold_rows = [r for r in rows if r["symbol"] == "طلا"]
latest = max(gold_rows, key=lambda r: r["captured_at"])
print(latest["payload"])
```

---

## 3) `archive/issued_units_history.jsonl`

این فایل تاریخچه تعداد واحدهای منتشرشده صندوق را نگه می‌دارد.

### نمونه رکورد

```json
{
  "captured_at": "2026-08-09T11:53:20.021586+00:00",
  "symbol": "عیار",
  "payload": {
    "symbol": "عیار",
    "units": 4803903416,
    "units_deven": "20260808",
    "as_of": "2026-08-09T11:52:52.863765+00:00",
    "nav_date": "2026-08-09",
    "status": "ok",
    "age_seconds": 34.3,
    "source": "tsetmc",
    "grain": "near_daily",
    "note": "etfIssuedUnit / etfUnitDeven — not Codal legs[].quantity; not tick-live"
  }
}
```

### فیلدهای سطح بالا

- `captured_at`: زمان ذخیره snapshot
- `symbol`: نماد صندوق
- `payload`: داده اصلی issued units

### فیلدهای مهم داخل `payload`

- `units`: تعداد واحدهای منتشرشده
- `units_deven`: تاریخ مرجع این عدد
- `as_of`: زمان دریافت
- `nav_date`: تاریخ NAV مربوط
- `status`: وضعیت رکورد
- `age_seconds`: سن داده برحسب ثانیه
- `source`: منبع، مثل `tsetmc`
- `grain`: نوع دقت داده، معمولاً `near_daily`
- `note`: توضیح درباره ماهیت این داده

### کاربرد

- کنترل NAV
- تحلیل dilution
- پایش تغییرات واحدهای منتشرشده

### نحوه استفاده

```python
import json

with open("archive/issued_units_history.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

gold_units = [r for r in rows if r["symbol"] == "طلا"]
latest = max(gold_units, key=lambda r: r["captured_at"])
print(latest["payload"]["units"])
```

---

## 4) `archive/ime_cdc_daily/*.jsonl`

این فایل‌ها تاریخچه روزانه IME CDC را نگه می‌دارند.  
فایل‌ها شامل:

- `GoldBar.jsonl`
- `GoldCoin.jsonl`
- `SilverBar.jsonl`

### نمونه رکورد

```json
{
  "captured_at": "2026-08-10T12:42:02.694902+00:00",
  "contract_code": "GoldBar",
  "trade_date": "2026-08-09",
  "persian_date": "1405/05/18",
  "trades_volume": 443218.0,
  "trades_value": 10994810094310.0,
  "max_price": 24880000.0,
  "min_price": 24620080.0,
  "last_price": 24839980.0,
  "first_price": 24620080.0,
  "open_interest": 307185773.0,
  "change_open_interest": 307935.0,
  "active_customers": 9968,
  "active_brokers": 93,
  "buyers": 273,
  "sellers": 122,
  "last_settlement_price": 24931684.0,
  "today_settlement_price": 24806777.0,
  "settlement_price_percent": -0.501,
  "vol_legal_buy": 355011.0,
  "vol_legal_sell": 416263.0,
  "vol_retail_buy": 88207.0,
  "vol_retail_sell": 26955.0
}
```

### فیلدها

- `captured_at`: زمان ذخیره رکورد
- `contract_code`: کد قرارداد
- `trade_date`: تاریخ میلادی معامله
- `persian_date`: تاریخ شمسی
- `trades_volume`: حجم معاملات
- `trades_value`: ارزش معاملات
- `max_price`: بیشترین قیمت روز
- `min_price`: کمترین قیمت روز
- `last_price`: آخرین قیمت روز
- `first_price`: اولین قیمت روز
- `open_interest`: موقعیت باز
- `change_open_interest`: تغییر open interest
- `active_customers`: تعداد مشتریان فعال
- `active_brokers`: تعداد کارگزاران فعال
- `buyers`: تعداد خریداران
- `sellers`: تعداد فروشندگان
- `last_settlement_price`: آخرین settlement
- `today_settlement_price`: settlement امروز
- `settlement_price_percent`: درصد تغییر settlement
- `vol_legal_buy`: حجم خرید حقوقی
- `vol_legal_sell`: حجم فروش حقوقی
- `vol_retail_buy`: حجم خرید حقیقی
- `vol_retail_sell`: حجم فروش حقیقی

### کاربرد

- ارزش‌گذاری IME
- کنترل قیمت شمش و سکه
- ورودی برای تحلیل NAV

### نحوه استفاده

```python
import json

with open("archive/ime_cdc_daily/GoldBar.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

latest = rows[-1]
print(latest["trade_date"], latest["last_price"])
```

---

## 5) `archive/coverage_report.json`

این فایل خلاصه کیفیت و پوشش داده‌ها را نگه می‌دارد.

### نمونه ساختار

```json
{
  "generated_at": "2026-08-12T10:00:00+00:00",
  "items": [
    {
      "name": "fund_bars_1m:طلا",
      "requested_from": "2026-07-13",
      "requested_to": "2026-08-12",
      "returned_rows": 16829,
      "unique_days": 31,
      "missing_days": 0,
      "notes": []
    }
  ],
  "totals": {
    "items": 10,
    "rows": 81705,
    "missing_days": 12
  },
  "missing_by_kind": {
    "fund_bars_1m": 12
  }
}
```

### فیلدها

- `generated_at`: زمان تولید گزارش
- `items`: لیست وضعیت هر collection item
- `totals`: جمع کل
- `missing_by_kind`: تعداد missing به تفکیک نوع داده

### داخل هر item

- `name`: نام dataset
- `requested_from`: ابتدای بازه درخواست
- `requested_to`: انتهای بازه درخواست
- `returned_rows`: تعداد ردیف‌های برگشتی
- `unique_days`: تعداد روزهای یکتا
- `missing_days`: تعداد روزهای missing
- `notes`: توضیحات تکمیلی

### کاربرد

- فهم سریع coverage
- تشخیص gap
- تصمیم برای backfill

### نحوه استفاده

```python
import json

with open("archive/coverage_report.json", "r", encoding="utf-8") as f:
    report = json.load(f)

print(report["totals"])
```

---

## 6) `archive/collect_data.log`

این فایل لاگ اجرای collector است.

### نمونه محتوا

```text
Captured 5 funds at 2026-08-10T12:00:00+00:00
[warn] holdings capture failed for طلا: ...
```

### فیلدها

این فایل ساختار JSON ندارد و یک لاگ متنی است.  
معمولاً شامل:

- زمان اجرا
- پیام موفقیت
- warningها
- errorها

### کاربرد

- audit
- debug
- بررسی اجرای روزانه collector

### نحوه استفاده

```bash
cat archive/collect_data.log
```

---

## 7) `merged_output/*.csv`

این فایل‌ها داده‌های چند منبع را در یک CSV ترکیب می‌کنند.  
برای هر صندوق یک فایل جدا وجود دارد:

- `طلا_merged.csv`
- `عیار_merged.csv`
- `کهربا_merged.csv`
- `مثقال_merged.csv`
- `آتش_merged.csv`

### این فایل‌ها چه چیزی دارند؟

معمولاً ترکیبی از:

- NAV history
- composition history
- USDT daily data
- IME data
- live holdings metadata

### کاربرد

- تحلیل آماده
- اکسل
- پژوهش
- joinهای سریع

### نحوه استفاده

```python
import pandas as pd

df = pd.read_csv("merged_output/طلا_merged.csv")
print(df.head())
```

---

## 8) نکته کاربردی

### برای آرشیو خام

- `archive/fund_bars_1m/*.jsonl`
- `archive/holdings_history.jsonl`
- `archive/issued_units_history.jsonl`
- `archive/ime_cdc_daily/*.jsonl`

### برای کنترل کیفیت

- `archive/coverage_report.json`
- `archive/collect_data.log`

### برای بک‌تست و تحلیل

- `merged_output/*.csv`

### برای backfill داده‌های ناقص

```bash
python3 -m fetch_data.collect_missing_data --days 180
```

