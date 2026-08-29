# گزارش استفاده از SDK و آرشیو داده‌های `goldarb-lab`

## 1) هدف پروژه
این پروژه یک SDK و مجموعه ابزار جمع‌آوری داده برای پلتفرم Gold Arbitrage است.  
هدف آن این است که داده‌های لازم برای:
- تحلیل صندوق‌ها
- بک‌تست **یک‌ثانیه‌ای** و دقیقه‌ای
- اجرای همان Strategy روی پیپر لایو سشن ایران
- محاسبه NAV حسابداری
- نگهداری تاریخچه point-in-time
- بررسی شکاف‌های داده

را به‌صورت منظم جمع‌آوری، ذخیره، و روی موتور بک‌تست / لایو اجرا کند.

راهنمای عملی SDK (Strategy، ماه ۱s، سشن ۱۲:۰۰–۱۷:۰۰): [`docs/sdk-usage-fa.md`](docs/sdk-usage-fa.md).

## 2) اجزای اصلی پروژه

### `src/goldarb`
هسته SDK است.
علاوه بر خواندن API، قرارداد `Strategy`، `BacktestEngine` / `LiveSimulationEngine`،
و پایپلاین‌های `month_backtest` / `iran_session_live` را دارد.

### `fetch_data`
مجموعه اسکریپت‌های جمع‌آوری و آرشیو داده است.  
این اسکریپت‌ها داده را می‌گیرند، ذخیره می‌کنند، و بعضی وقت‌ها گزارش coverage هم می‌سازند.

### `archive`
آرشیو خام داده‌ها است.  
داده‌های تاریخی و snapshotها اینجا ذخیره می‌شوند.

### `merged_output`
فایل‌های ترکیبی و آماده تحلیل را نگه می‌دارد.  
این فایل‌ها معمولاً از ترکیب NAV، composition، USDT، و بعضی داده‌های IME ساخته می‌شوند.

## 3) نوع داده‌هایی که الان داریم

### 3.1 `archive/fund_bars_1m/*.jsonl`
این فایل‌ها داده‌های یک‌دقیقه‌ای صندوق‌ها را نگه می‌دارند.

صندوق‌ها:
- `طلا`
- `عیار`
- `کهربا`
- `مثقال`
- `آتش`

هر رکورد معمولاً شامل این فیلدهاست:
- `bar_at`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `nav_price`
- `premium_discount_pct`
- `captured_at`

#### کاربرد
- بک‌تست دقیقه‌ای
- بررسی gap
- تحلیل قیمت و premium

#### نحوه استفاده
```python
import json

with open("archive/fund_bars_1m/طلا.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
```

### 3.2 `archive/holdings_history.jsonl`
این فایل تاریخچه snapshot ترکیب دارایی صندوق‌ها را نگه می‌دارد.

هر رکورد معمولاً شامل:
- `captured_at`
- `symbol`
- `payload`

داخل `payload` معمولاً اطلاعاتی مثل:
- `as_of`
- `source`
- `legs`
- درصد وزن هر دارایی
- اطلاعات کدال یا composition

#### کاربرد
- تحلیل point-in-time پرتفوی
- بررسی composition صندوق
- کمک به NAV حسابداری

#### نحوه استفاده
```python
import json

with open("archive/holdings_history.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
```

مثال:
```python
gold_rows = [r for r in rows if r["symbol"] == "طلا"]
latest = max(gold_rows, key=lambda r: r["captured_at"])
print(latest["payload"])
```

### 3.3 `archive/issued_units_history.jsonl`
این فایل تاریخچه تعداد واحدهای منتشرشده صندوق را نگه می‌دارد.

هر رکورد معمولاً شامل:
- `captured_at`
- `symbol`
- `payload`

داخل `payload` معمولاً:
- `units`
- `units_deven`
- `as_of`
- `source`
- `age_seconds`

#### کاربرد
- بررسی تغییرات issued units
- محاسبه NAV
- تحلیل dilution

#### نحوه استفاده
```python
import json

with open("archive/issued_units_history.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
```

مثال:
```python
gold_units = [r for r in rows if r["symbol"] == "طلا"]
latest = max(gold_units, key=lambda r: r["captured_at"])
print(latest["payload"]["units"])
```

### 3.4 `archive/ime_cdc_daily/*.jsonl`
این فایل‌ها تاریخچه روزانه IME CDC را نگه می‌دارند.

فایل‌ها:
- `GoldBar.jsonl`
- `GoldCoin.jsonl`
- `SilverBar.jsonl`

هر رکورد شامل:
- `contract_code`
- `trade_date`
- `last_price`
- `today_settlement_price`
- `trades_volume`
- `trades_value`
- `open_interest`
- `buyers`
- `sellers`
- و فیلدهای دیگر

#### کاربرد
- تحلیل روزانه بازار IME
- کنترل قیمت شمش و سکه
- ورودی برای NAV و ارزش‌گذاری

#### نحوه استفاده
```python
import json

with open("archive/ime_cdc_daily/GoldBar.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
```

مثال:
```python
latest = rows[-1]
print(latest["trade_date"], latest["last_price"])
```

### 3.5 `archive/coverage_report.json`
این فایل خلاصه کیفیت و پوشش داده را نگه می‌دارد.

معمولاً شامل:
- بازه درخواست‌شده
- تعداد ردیف‌های برگردانده‌شده
- تعداد روزهای یکتا
- تعداد روزهای missing
- جمع کل coverage
- تفکیک بر اساس نوع داده

#### کاربرد
- بررسی اینکه چقدر داده داریم
- فهمیدن gapها
- تصمیم برای backfill

#### نحوه استفاده
```python
import json

with open("archive/coverage_report.json", "r", encoding="utf-8") as f:
    report = json.load(f)

print(report["totals"])
```

### 3.6 `archive/collect_data.log`
این فایل لاگ اجرای collector است.

#### کاربرد
- بررسی روند اجرا
- پیدا کردن warning یا خطا
- audit عملیات جمع‌آوری داده

#### نحوه استفاده
```bash
cat archive/collect_data.log
```

## 4) فایل‌های ترکیبی `merged_output`

### `merged_output/*.csv`
این فایل‌ها داده‌های چند منبع را در یک CSV ترکیب می‌کنند.

برای هر صندوق یک فایل وجود دارد:
- `طلا_merged.csv`
- `عیار_merged.csv`
- `کهربا_merged.csv`
- `مثقال_merged.csv`
- `آتش_merged.csv`

#### این فایل‌ها چه چیزی دارند؟
معمولاً ترکیبی از:
- NAV history
- composition history
- USDT daily data
- IME data
- live holdings metadata

#### کاربرد
- تحلیل آماده
- اکسل
- پژوهش
- joinهای سریع

#### نحوه استفاده
```python
import pandas as pd

df = pd.read_csv("merged_output/طلا_merged.csv")
print(df.head())
```

## 5) اسکریپت‌های مهم در `fetch_data`

### 5.1 `fetch_data/collect_missing_data.py`
این اسکریپت برای جمع‌کردن داده‌های missing طراحی شده است.

کارهایی که انجام می‌دهد:
- 1m bars صندوق‌ها را جمع می‌کند
- holdings snapshot را جمع می‌کند
- issued units snapshot را جمع می‌کند
- IME daily history را جمع می‌کند
- coverage report می‌سازد
- minute gap report می‌سازد

#### اجرا
```bash
python3 -m fetch_data.collect_missing_data --days 180
```

#### خروجی
- `archive/missing_data/...`
- `archive/missing_data/coverage_report.json`
- `archive/missing_data/minute_gap_report.json`

#### کاربرد
برای backfill و پیدا کردن داده‌های ناقص.

### 5.2 `fetch_data/daily_archive.py`
این اسکریپت snapshot روزانه holdings و issued units را ذخیره می‌کند.

#### اجرا
```bash
python3 -m fetch_data.daily_archive
```

#### خروجی
- `archive/holdings_history.jsonl`
- `archive/issued_units_history.jsonl`

### 5.3 `fetch_data/minute_bar_archive.py`
این اسکریپت 1m bars صندوق‌ها را ذخیره می‌کند.

#### اجرا
```bash
python3 -m fetch_data.minute_bar_archive
```

#### خروجی
- `archive/fund_bars_1m/*.jsonl`

### 5.4 `fetch_data/ime_cdc_archive.py`
این اسکریپت archive بلندمدت IME daily history را نگه می‌دارد.

#### اجرا
```bash
python3 -m fetch_data.ime_cdc_archive
```

#### خروجی
- `archive/ime_cdc_daily/GoldBar.jsonl`
- `archive/ime_cdc_daily/GoldCoin.jsonl`

### 5.5 `fetch_data/fetch_ime_cdc_history.py`
این اسکریپت یک export کوتاه‌مدت 180 روزه از IME daily history می‌دهد.

#### اجرا
```bash
python3 -m fetch_data.fetch_ime_cdc_history
```

#### خروجی
- `ime_cdc_history.jsonl`
- `ime_cdc_history.csv`

### 5.6 `fetch_data/run_all.py`
همه جریان‌های اصلی fetch را پشت سر هم اجرا می‌کند.

#### اجرا
```bash
python3 -m fetch_data.run_all
```

#### کاربرد
وقتی بخواهی همه چیز را یکجا بگیری.

## 6) نحوه خواندن داده‌ها

### JSONL چیست؟
JSONL یعنی هر خط یک JSON جداست.  
برای خواندنش:
```python
import json

with open("file.jsonl", "r", encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if line.strip()]
```

### CSV چیست؟
CSV را با pandas می‌خوانیم:
```python
import pandas as pd

df = pd.read_csv("file.csv")
```

## 7) نحوه استفاده از SDK

سند کامل: [`docs/sdk-usage-fa.md`](docs/sdk-usage-fa.md).

### ساخت client
```python
from goldarb import LabClient

with LabClient.from_env() as client:
    pass
```

### مثال گرفتن داده صندوق
```python
with LabClient.from_env() as client:
    bars = client.fund.candles("طلا", start="2026-07-01", end="2026-07-03", grain="1s")
    holdings = client.fund.holdings("طلا")
    units = client.fund.issued_units("طلا")
```

`grain` می‌تواند `1s`، `1m`، یا `daily` باشد. برای استراتژی جفت از `1s` استفاده کنید.

### مثال گرفتن داده بازار
```python
with LabClient.from_env() as client:
    usdt = client.market.usdt_live()
    xau = client.market.xau(start="2026-07-01", end="2026-07-03", grain="1m")
    ime = client.market.ime_cdc_stats("GoldBar", days=180)
```

### بک‌تست ماه ۱s سپس سشن لایو ایران
```python
from goldarb import BubbleRankStrategy, LabClient, iran_session_live, month_backtest

strategy = BubbleRankStrategy()
with LabClient.from_env() as client:
    month = month_backtest(strategy, client, days=30, grain="1s", fill_session=True)
    live = iran_session_live(
        strategy, client, poll_seconds=1.0, lookback_days=0, include_session_bars=False
    )
```

پوشش یک ثانیه اجباری است: `fill_session=True` هر ثانیهٔ ۱۲:۰۰–۱۷:۰۰ تهران را روی روزهای دارای داده پخش می‌کند؛ لایو با `poll_seconds=1.0` تا پایان سشن پول می‌کند.

## 8) گزارش وضعیت داده‌ها نسبت به دو document

### چیزهایی که الان داریم
- 1m bars صندوق‌ها
- holdings snapshot
- issued units snapshot
- IME daily history
- coverage report
- minute gap report
- merged CSVها

### چیزهایی که هنوز ناقص‌اند
- point-in-time holdings revisions کامل با `published_at`
- full accounting NAV components
- historical IME contract metadata
- exact `no_trade / missing / halted`
- historical order book
- backend bulk bars-many با coverage metadata

## 9) بهترین مسیر استفاده برای تیم
اگر هدف تیم این باشد که از داده‌ها برای تحلیل و بک‌تست استفاده کند، این ترتیب خوب است:

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
- مسیر Strategy روی `grain=1s`: `month_backtest` سپس `iran_session_live` (سند: `docs/sdk-usage-fa.md`)

### برای backfill داده‌های missing
```bash
python3 -m fetch_data.collect_missing_data --days 180
```

## 10) جمع‌بندی
این پروژه الان چهار کار اصلی می‌کند:
1. داده را از SDK/API می‌گیرد
2. آن را در archive نگه می‌دارد
3. فایل‌های ترکیبی و coverage report برای تحلیل می‌سازد
4. همان Strategy را روی بک‌تست ۱s و پیپر لایو سشن ایران اجرا می‌کند

