# گزارش رسمی وضعیت SDK و آرشیو داده‌ها برای تیم لید

**موضوع:** وضعیت فعلی SDK، ساختار کامل داده‌های آرشیو، شکاف‌های باقی‌مانده، و مسیر اجرایی پیشنهادی
**پروژه:** `goldarb-lab`
**تاریخ:** 2026-08-12

---

## 1) خلاصه مدیریتی

SDK و ابزارهای جمع‌آوری داده برای پلتفرم Gold Arbitrage تا حد قابل‌توجهی آماده شده‌اند و بخش مهمی از داده‌های موردنیاز برای تحلیل، بک‌تست، و آرشیو تاریخی در پروژه ذخیره شده است.

**آنچه اکنون در اختیار داریم:**

- داده‌های یک‌دقیقه‌ای (1m) پنج صندوق اصلی
- تاریخچه snapshot از holdings و issued units
- تاریخچه روزانه IME برای GoldBar / GoldCoin / SilverBar
- فایل‌های ترکیبی آماده تحلیل در `merged_output`
- گزارش‌های coverage و gap برای شناسایی داده‌های ناقص
- مستندسازی کامل ساختار و فیلدهای هر فایل خروجی (بخش ۳ این گزارش)

**آنچه هنوز کامل نیست** (جزئیات در بخش ۴): point-in-time واقعی holdings با `published_at`، اجزای کامل NAV حسابداری، متادیتای تاریخی قراردادهای IME، وضعیت دقیق `no_trade/missing/halted` در سطح دقیقه، و تاریخچه order book.

---

## 2) وضعیت collectorها

| اسکریپت | وظیفه | خروجی |
|---|---|---|
| `fetch_data/collect_data.py` | جمع‌آوری همه‌جانبه: 1m bars صندوق‌ها + holdings + issued units + IME daily + تولید coverage report | مستقیماً در `archive/...` |
| `fetch_data/daily_archive.py` | آرشیو snapshot روزانه holdings و issued units (نسخه اولیه/مستقل) | `archive/holdings_history.jsonl`, `archive/issued_units_history.jsonl` |
| `fetch_data/minute_bar_archive.py` | آرشیو 1m bars صندوق‌ها (نسخه اولیه/مستقل) | `archive/fund_bars_1m/*.jsonl` |
| `fetch_data/ime_cdc_archive.py` | آرشیو بلندمدت IME daily (نسخه اولیه/مستقل) | `archive/ime_cdc_daily/*.jsonl` |
| `fetch_data/fetch_ime_cdc_history.py` | export یک‌باره و کوتاه‌مدت (۱۸۰ روزه، سقف پلتفرم) IME daily | `ime_cdc_history.jsonl`, `ime_cdc_history.csv` (خارج از archive/) |
| `fetch_data/merge_fund_datasets.py` | ادغام CSVهای محلی (NAV، composition، USDT) با داده زنده SDK | `merged_output/*.csv` |
| `fetch_data/check_session_start_gap.py` | ابزار تشخیصی برای بررسی نقطه شروع داده روزانه صندوق‌ها | چاپ در کنسول (بدون فایل خروجی) |
| `fetch_data/inspect_ime_cdc_stats.py` | ابزار تشخیصی برای بررسی ساختار خام پاسخ IME | چاپ در کنسول |

**توصیه اجرایی:** `collect_data.py` جایگزین کامل سه اسکریپت `daily_archive.py`، `minute_bar_archive.py`، و `ime_cdc_archive.py` است و تنها اسکریپتی است که باید روی cron زمان‌بندی شود. سه اسکریپت قبلی برای اجرای دستی/مرجع نگه داشته شده‌اند اما نباید همزمان با `collect_data.py` زمان‌بندی شوند — اجرای همزمان باعث دو آرشیو موازی و واگرا می‌شود (این دقیقاً همان مشکلی بود که یک‌بار در این پروژه رخ داد و با اسکریپت ادغام یک‌باره رفع شد).

**اجرا:**
```bash
python3 -m fetch_data.collect_data --days 30
```

---

## 3) راهنمای کامل فایل‌های داده تولیدشده

### 3.1 `archive/fund_bars_1m/*.jsonl`

داده‌های یک‌دقیقه‌ای صندوق‌ها. یک فایل جداگانه برای هر صندوق:
`طلا.jsonl`، `عیار.jsonl`، `کهربا.jsonl`، `مثقال.jsonl`، `آتش.jsonl`

**نمونه رکورد:**
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

**فیلدها:**
| فیلد | توضیح |
|---|---|
| `captured_at` | زمان ذخیره‌شدن رکورد در آرشیو |
| `symbol` | نماد صندوق |
| `bar_at` | زمان همان کندل دقیقه‌ای |
| `open` / `high` / `low` / `close` | قیمت باز شدن / بیشترین / کمترین / بسته شدن |
| `volume` | حجم معامله |
| `nav_price` | NAV همان لحظه، در صورت موجود بودن |
| `premium_discount_pct` | درصد premium یا discount نسبت به NAV |

**کاربرد:** بک‌تست دقیقه‌ای، بررسی شکاف داده، تحلیل premium و رفتار صندوق.

**نحوه استفاده:**
```python
import json

with open("archive/fund_bars_1m/طلا.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

latest = rows[-1]
print(latest["bar_at"], latest["close"])
```

⚠️ **محدودیت شناخته‌شده:** داده‌های این فایل‌ها به‌طور مکرر از ساعت 08:30 UTC (نه 05:30 UTC که معادل شروع رسمی جلسه معاملاتی ۰۹:۰۰ به وقت تهران است) شروع می‌شوند — این الگو در تمام ۵ صندوق و چند روز مختلف تأیید شده و نیازمند پیگیری با تیم پلتفرم است (نگاه کنید به بخش ۴.۵).

---

### 3.2 `archive/holdings_history.jsonl`

تاریخچه snapshot ترکیب دارایی (composition) صندوق‌ها.

**نمونه رکورد:**
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
    "legs": ["..."]
  }
}
```

**فیلدهای سطح بالا:** `captured_at`، `symbol`، `payload`

**فیلدهای مهم داخل `payload`:**
| فیلد | توضیح |
|---|---|
| `ins_code` | کد instrument صندوق |
| `status` | وضعیت رکورد (مثل `ok`) |
| `as_of` | تاریخ مرجع پرتفوی |
| `age_days` | فاصله روز فعلی تا تاریخ مرجع |
| `stale_after_days` | آستانه stale‌شدن داده |
| `fetched_at` | زمان دریافت از منبع (**توجه:** این معادل `published_at` نیست — نگاه کنید به بخش ۴.۱) |
| `source` | منبع داده (مثل `codal_monthly_portfolio`) |
| `quality` | کیفیت داده (مثل `official`) |
| `legs` | لیست دارایی‌های صندوق |

**داخل هر `leg`:** `leg_type` (مثل `gold_bar_cert`، `gold_coin_cert`، `silver_bar_cert`)، `quantity`، `weight_pct`، `raw_label_fa`

**کاربرد:** بررسی composition صندوق، تحلیل point-in-time، ورودی محاسبه NAV حسابداری.

**نحوه استفاده:**
```python
import json

with open("archive/holdings_history.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

gold_rows = [r for r in rows if r["symbol"] == "طلا"]
latest = max(gold_rows, key=lambda r: r["captured_at"])
print(latest["payload"])
```

⚠️ **محدودیت شناخته‌شده:** این فایل صرفاً **آرشیو snapshotهای گرفته‌شده از این پروژه به بعد** است، نه تاریخچه واقعی نسخه‌های Codal. برای تاریخ‌های قبل از شروع جمع‌آوری داده، هیچ داده‌ای وجود ندارد و غیرقابل‌بازیابی است.

---

### 3.3 `archive/issued_units_history.jsonl`

تاریخچه snapshot تعداد واحدهای منتشرشده صندوق.

**نمونه رکورد:**
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

**فیلدهای مهم داخل `payload`:**
| فیلد | توضیح |
|---|---|
| `units` | تعداد واحدهای منتشرشده |
| `units_deven` | تاریخ مرجع این عدد (TSETMC) |
| `as_of` | زمان دریافت |
| `nav_date` | تاریخ NAV مربوطه |
| `source` | منبع (`tsetmc`) |
| `grain` | دقت داده، معمولاً `near_daily` — **نه تیک‌به‌تیک** |
| `note` | توضیح صریح که این عدد معادل `legs[].quantity` کدال نیست |

**کاربرد:** کنترل NAV، تحلیل dilution، پایش تغییرات واحدهای منتشرشده.

**نحوه استفاده:**
```python
import json

with open("archive/issued_units_history.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

gold_units = [r for r in rows if r["symbol"] == "طلا"]
latest = max(gold_units, key=lambda r: r["captured_at"])
print(latest["payload"]["units"])
```

⚠️ **محدودیت مهم:** این عدد **کل واحدهای منتشرشده صندوق** است، نه واحدهای نزد یک سرمایه‌گذار خاص. اگر نیاز به موجودی یک حساب مشخص است، این فایل پاسخگو نیست.

---

### 3.4 `archive/ime_cdc_daily/*.jsonl`

تاریخچه روزانه IME CDC. فایل‌ها: `GoldBar.jsonl`، `GoldCoin.jsonl`، `SilverBar.jsonl`

**نمونه رکورد:**
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

**فیلدها:**
| فیلد | توضیح |
|---|---|
| `contract_code` | کد قرارداد |
| `trade_date` / `persian_date` | تاریخ میلادی / شمسی معامله |
| `trades_volume` / `trades_value` | حجم و ارزش معاملات |
| `max_price` / `min_price` / `last_price` / `first_price` | بالاترین/پایین‌ترین/آخرین/اولین قیمت روز |
| `open_interest` / `change_open_interest` | موقعیت باز و تغییر آن |
| `active_customers` / `active_brokers` / `buyers` / `sellers` | آمار مشارکت بازار |
| `last_settlement_price` / `today_settlement_price` / `settlement_price_percent` | قیمت‌های تسویه |
| `vol_legal_buy` / `vol_legal_sell` / `vol_retail_buy` / `vol_retail_sell` | حجم خرید/فروش حقوقی و حقیقی |

**کاربرد:** ارزش‌گذاری IME، کنترل قیمت شمش و سکه، ورودی تحلیل NAV.

**نحوه استفاده:**
```python
import json

with open("archive/ime_cdc_daily/GoldBar.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]

latest = rows[-1]
print(latest["trade_date"], latest["last_price"])
```

⚠️ **محدودیت شناخته‌شده:** endpoint زیرین این داده حداکثر ۱۸۰ روز عقب‌تر را در هر فراخوانی برمی‌گرداند (سقف پلتفرم). آرشیو این فایل با اجرای منظم (روزانه) این محدودیت را دور می‌زند و به‌مرور بیش از ۱۸۰ روز پوشش می‌دهد، اما تاریخ‌های قبل از شروع آرشیو غیرقابل‌بازیابی هستند. همچنین فیلدهای `contract_multiplier`، `certificate_to_gram`، `purity`، `currency`، `price_unit` در این داده **موجود نیستند** (نگاه کنید به بخش ۴.۴).

---

### 3.5 `archive/coverage_report.json`

خلاصه کیفیت و پوشش داده‌ها — تولید‌شده در هر اجرای `collect_data.py`.

**نمونه ساختار:**
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

**فیلدها:** `generated_at`، `items` (وضعیت هر مجموعه‌داده)، `totals`، `missing_by_kind`

**داخل هر `item`:** `name`، `requested_from`/`requested_to`، `returned_rows`، `unique_days`، `missing_days`، `notes`

**کاربرد:** فهم سریع coverage، تشخیص gap، تصمیم‌گیری برای backfill.

**نحوه استفاده:**
```python
import json

with open("archive/coverage_report.json", "r", encoding="utf-8") as f:
    report = json.load(f)

print(report["totals"])
```

⚠️ **نکته مهم برای تفسیر:** عدد `missing_days` به‌تنهایی نباید به‌عنوان «مشکل» تفسیر شود — بخش زیادی از این اعداد معمولاً مربوط به روزهای تعطیل (پنج‌شنبه/جمعه در تقویم Sat–Wed) است، نه شکاف واقعی داده. برای تفکیک دقیق «تعطیل واقعی» از «شکاف واقعی»، لازم است تاریخ هر `missing_day` به‌صورت دستی یا خودکار با روز هفته مقایسه شود (نمونه بررسی این موضوع در بخش ۴.۵ آمده).

---

### 3.6 `archive/collect_data.log`

لاگ اجرای collector.

**نمونه محتوا:**
```text
Captured 5 funds at 2026-08-10T12:00:00+00:00
[warn] holdings capture failed for طلا: ...
```

فایل ساختار JSON ندارد؛ لاگ متنی شامل زمان اجرا، پیام موفقیت، warningها و errorها.

**کاربرد:** audit، دیباگ، بررسی اجرای روزانه.

**نحوه استفاده:**
```bash
cat archive/collect_data.log
```

---

### 3.7 `merged_output/*.csv`

فایل‌های ترکیبی چندمنبعی — یکی برای هر صندوق: `طلا_merged.csv`، `عیار_merged.csv`، `کهربا_merged.csv`، `مثقال_merged.csv`، `آتش_merged.csv`

**محتوا:** ترکیبی از NAV history (از CSV محلی)، composition history (از CSV محلی)، داده روزانه USDT، داده IME مربوطه (بر اساس `leg_type` واقعی هر صندوق)، و metadata زنده holdings از SDK.

**کاربرد:** تحلیل آماده، Excel، پژوهش، joinهای سریع.

**نحوه استفاده:**
```python
import pandas as pd

df = pd.read_csv("merged_output/طلا_merged.csv")
print(df.head())
```

⚠️ **محدودیت شناخته‌شده:** ستون `gold_legs_weight_pct` در این فایل یک عدد **ثابت** (آخرین snapshot موجود) است، نه سری تاریخی واقعی — فقط برای ردیف نزدیک به تاریخ `legs_as_of` قابل اتکاست، نه برای کل تاریخچه.

---

## 4) شکاف‌های باقی‌مانده (نیازمند اقدام backend/تیم پلتفرم)

### 4.1 Holdings history با `published_at` واقعی
فیلدهای موردنیاز: `portfolio_as_of`، `published_at`، `fetched_at`، `revision_id`، `source`. در حال حاضر فقط `fetched_at` (زمان دریافت توسط ما) وجود دارد، نه `published_at` واقعی (زمان انتشار توسط کدال) — این تفاوت ریسک look-ahead bias ایجاد می‌کند.

### 4.2 Issued-units history کامل
فیلدهای موردنیاز: `effective_date`، `published_at`، `created_units`، `cancelled_units`، `source`. در حال حاضر فقط snapshot لحظه‌ای «کل واحدها» موجود است.

### 4.3 اجزای کامل NAV حسابداری
فیلدهای موردنیاز: `cash_irr`، `bank_deposits_irr`، `receivables_irr`، `dividends_receivable_irr`، `other_assets_irr`، `payables_irr`، `management_fee_payable_irr`، `custodian_fee_payable_irr`، `tax_payable_irr`، `other_liabilities_irr`، `accrued_expenses_irr`. هیچ‌کدام در SDK یا API فعلی موجود نیست.

### 4.4 متادیتای تاریخی قراردادهای IME
جدول مرجع موردنیاز: `contract_code`، `valid_from`، `valid_to`، `contract_multiplier`، `certificate_to_gram`، `purity`، `coin_type`، `currency`، `price_unit`. بدون این جدول، خطر خطای واحد در ارزش‌گذاری وجود دارد.

### 4.5 وضعیت دقیق minute-level (`available` / `no_trade` / `missing` / `halted`)
در حال حاضر coverage_report فقط تعداد را گزارش می‌دهد، نه علت. یک یافته واقعی و تأییدشده در این پروژه:

> داده‌های 1m صندوق‌ها به‌طور مکرر و در چند روز مختلف از ساعت **۰۸:۳۰ UTC** (نه ۰۵:۳۰ UTC معادل شروع رسمی ۰۹:۰۰ تهران) شروع می‌شوند — الگویی یکسان در هر ۵ صندوق. بازه پایانی جلسه (۱۳:۲۹–۱۳:۳۰ UTC ≈ ۱۷:۰۰ تهران) صحیح است؛ فقط ابتدای جلسه کوتاه‌شده. این یافته باید مستقیماً با تیم پلتفرم پیگیری شود: آیا این بازه واقعاً بدون معامله است یا یک محدودیت ingestion؟

### 4.6 تاریخچه order book
در حال حاضر order book فقط لحظه‌ای (live) در دسترس است؛ هیچ history API برای آن وجود ندارد.

### 4.7 Endpoint یکجای بازیابی چندنمادی (bulk) با coverage metadata
در SDK فعلی، عملکرد چندنمادی (`candles_many`) صرفاً یک حلقه client-side روی endpoint تک‌نمادی است — endpoint واقعی bulk با پارامتر `as_known_at` و metadata پوشش (`coverage_pct`, `missing_intervals`, `quality_status`) هنوز وجود ندارد.

---

## 5) اقدامات انجام‌شده در این مرحله

1. ساخت و اصلاح collectorهای داده (`daily_archive.py`، `minute_bar_archive.py`، `ime_cdc_archive.py`، و در نهایت تجمیع در `collect_data.py`)
2. ایجاد آرشیو point-in-time (append-only) برای holdings و issued units
3. ایجاد آرشیو بلندمدت IME daily برای دور زدن محدودیت ۱۸۰ روزه endpoint
4. ساخت coverage_report.json برای شناسایی خودکار روزهای گم‌شده
5. کشف و تأیید یافته واقعی «شکاف ۰۸:۳۰ UTC» با شواهد مستقل روی هر ۵ صندوق
6. رفع باگ محاسبه coverage (شمارش نادرست روزهای از قبل آرشیوشده به‌عنوان «گم‌شده»)
7. تشخیص و ادغام دو آرشیو موازی (`archive/` و `archive/missing_data/`) بدون از‌دست‌دادن داده — آرشیو دوم عمق تاریخی بیشتری داشت که با اسکریپت ادغام حفظ شد
8. مستندسازی کامل ساختار و فیلدهای هر فایل خروجی (بخش ۳ این گزارش)

---

## 6) ساختار استفاده پیشنهادی برای تیم

| هدف | فایل‌ها |
|---|---|
| آرشیو خام | `archive/fund_bars_1m/*.jsonl`, `archive/holdings_history.jsonl`, `archive/issued_units_history.jsonl`, `archive/ime_cdc_daily/*.jsonl` |
| کنترل کیفیت | `archive/coverage_report.json`, `archive/collect_data.log` |
| تحلیل و بک‌تست | `merged_output/*.csv` |
| backfill داده‌های ناقص | `python3 -m fetch_data.collect_data --days 180` |

---

## 7) جمع‌بندی اجرایی

پروژه در وضعیت فعلی برای جمع‌آوری و نگهداری بخش مهمی از داده‌های موردنیاز آماده است. با این حال، برای استفاده کامل در NAV حسابداری مستقل، بک‌تست دقیقه‌ای معتبر، و تحلیل point-in-time بدون look-ahead، هنوز لازم است چند منبع داده و metadata کلیدی (بخش ۴) در backend یا لایه آرشیو تکمیل شوند. هیچ‌کدام از این موارد از سمت client-side (SDK یا اسکریپت‌های `fetch_data`) قابل‌حل نیستند — نیازمند تصمیم و اقدام تیم پلتفرم هستند.

---

## 8) پیشنهاد اقدام بعدی، به ترتیب اولویت

1. تکمیل holdings history با `published_at` واقعی (بخش ۴.۱)
2. تکمیل issued-units history با جزئیات صدور/ابطال (بخش ۴.۲)
3. افزودن اجزای NAV حسابداری (بخش ۴.۳)
4. تهیه جدول مرجع متادیتای قراردادهای IME (بخش ۴.۴)
5. پیگیری یافته «شکاف ۰۸:۳۰ UTC» با تیم پلتفرم (بخش ۴.۵) — این مورد شواهد مستند و آماده ارسال دارد
6. استانداردسازی وضعیت دقیقه‌ای به `available / no_trade / missing / halted`
7. تعریف یا درخواست endpointهای رسمی برای metadata و historyهای باقی‌مانده (bulk bars-many، portfolio-history، issued-units-history)

---

## 9) نتیجه نهایی

این پروژه اکنون یک پایه عملیاتی قابل‌اتکا برای جمع‌آوری، آرشیو، و تحلیل اولیه داده فراهم کرده است — شامل مکانیزم‌های خودترمیم (dedup، coverage tracking) و مستندسازی کامل ساختار داده. برای رسیدن به سطح کامل و قابل‌اتکا در گزارش‌های NAV حسابداری مستقل و بک‌تست دقیقه‌ای معتبر، تکمیل شکاف‌های داده‌ای بخش ۴ ضروری است و این موارد باید در قالب یک درخواست رسمی به تیم پلتفرم/backend ارجاع شوند.