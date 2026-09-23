# سند نیازمندی‌های SDK پروژه GoldArb Lab

**Project:** `goldarb-lab`
**Related System:** `goldarb`
**Document Type:** Software Requirements Specification (SRS)
**Version:** 0.1
**Status:** Draft

---

## 1. مقدمه

### 1.1 هدف پروژه

`goldarb-lab` یک SDK و محیط آزمایش استراتژی‌های معاملاتی است که با هدف توسعه، تست و ارزیابی Strategyهای آربیتراژ در بازار ایران طراحی می‌شود.

سیستم اصلی `goldarb` مسئول دریافت، پالایش و ذخیره‌سازی داده‌های بازار به‌صورت Real-Time است. این داده‌ها در PostgreSQL ذخیره شده و از طریق API در اختیار `goldarb-lab` قرار می‌گیرند.

هدف `goldarb-lab` این است که تیم Trading بتواند یک Strategy را بدون تغییر اساسی در کد در محیط‌های مختلف اجرا و ارزیابی کند:

1. Historical Backtest
2. Live Market Simulation / Paper Trading
3. در آینده Live Trading واقعی

### 1.2 سند استفاده

راهنمای عملی نصب، قرارداد Strategy، بک‌تست ماهانه با پوشش **یک ثانیه**، و پیپر لایو سشن ۱۲:۰۰–۱۸:۰۰ تهران (شنبه تا چهارشنبه):

[`docs/sdk-usage-fa.md`](sdk-usage-fa.md)

---

## 2. اهداف اصلی

سیستم باید امکان موارد زیر را فراهم کند:

* اجرای Strategy روی داده‌های تاریخی
* اجرای همان Strategy روی داده‌های Real-Time
* شبیه‌سازی کامل چرخه سفارش
* شبیه‌سازی کارمزد
* شبیه‌سازی Slippage
* شبیه‌سازی Bid/Ask
* شبیه‌سازی Order Book
* شبیه‌سازی Partial Fill
* شبیه‌سازی Latency
* مدیریت Portfolio
* محاسبه Realized و Unrealized PnL
* ثبت کامل معاملات و سفارش‌ها
* تحلیل عملکرد Strategy
* ثبت و تحلیل فرصت‌های Arbitrage
* قابلیت Reproduce کردن یک Backtest
* فراهم کردن مسیر انتقال Strategy از Backtest به Live Simulation و در نهایت Live Trading

---

## 3. معماری مفهومی

معماری مفهومی سیستم به صورت زیر در نظر گرفته می‌شود:

```text
                       goldarb
                          │
                 Real-Time Market Data
                          │
                    PostgreSQL
                          │
                         API
                          │
          ┌───────────────┴────────────────┐
          │                                │
          ▼                                ▼
   Historical Data                    Live Data
          │                                │
          ▼                                ▼
   ┌───────────────┐              ┌────────────────┐
   │ Backtest      │              │ Live Simulator │
   │ Engine        │              │                │
   └───────┬───────┘              └───────┬────────┘
           │                              │
           └──────────────┬───────────────┘
                          ▼
                      Strategy
                          │
                          ▼
                     Order Manager
                          │
                          ▼
                  Execution Simulator
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
          Orders       Fills       Positions
             │            │            │
             └────────────┼────────────┘
                          ▼
                      Portfolio
                          │
                          ▼
                    PnL / Metrics
                          │
                          ▼
                    Report / Analysis
```

---

## 4. اصل معماری کلیدی

### 4.1 Strategy باید Environment-Agnostic باشد

یک Strategy نباید بداند که در حال اجرا روی:

* Historical Data
* Live Data
* Paper Trading
* Live Trading

است.

برای مثال:

```python
class BubbleStrategy:

    def on_market_data(self, market):
        ...
```

همین Strategy باید بتواند توسط:

```text
BacktestEngine
LiveSimulationEngine
LiveTradingEngine
```

اجرا شود.

تفاوت محیط باید توسط Engine و Infrastructure کنترل شود، نه توسط Strategy.

---

## 5. محیط‌های اجرای Strategy

### 5.1 Backtest

Backtest باید Strategy را روی داده‌های تاریخی اجرا کند.

ورودی‌ها:

* Strategy
* Start Time
* End Time
* Initial Capital
* Data Source
* Fee Model
* Slippage Model
* Latency Model
* Execution Model
* Configuration

خروجی‌ها:

* Orders
* Executions
* Positions
* Portfolio
* PnL
* Metrics
* Arbitrage Opportunities
* Backtest Report

### 5.2 Live Simulation

Live Simulation باید همان Strategy را روی داده‌های Real-Time اجرا کند.

جریان سیستم:

```text
Market
  ↓
goldarb
  ↓
API
  ↓
Live Data Provider
  ↓
Strategy
  ↓
Signal
  ↓
Order
  ↓
Execution Simulator
  ↓
Fill
  ↓
Portfolio
  ↓
PnL
```

در این Mode هیچ سفارش واقعی به بازار ارسال نمی‌شود.

هدف این Mode بررسی عملکرد Strategy در شرایط واقعی بازار بدون ریسک سرمایه واقعی است.

### 5.3 Live Trading

در آینده Strategy باید بتواند بدون تغییر اساسی وارد محیط Live Trading شود.

جریان:

```text
Market Data
    ↓
Strategy
    ↓
Order
    ↓
Real Broker / Exchange
    ↓
Execution
    ↓
Portfolio
```

بنابراین Execution Layer باید از ابتدا طوری طراحی شود که Simulator و Real Broker قابل جایگزینی باشند.

---

## 6. Data Requirements

### 6.1 Historical Data

SDK باید بتواند داده تاریخی را از API پروژه `goldarb` دریافت کند.

حداقل قابلیت‌ها:

* انتخاب Symbol
* انتخاب بازه زمانی
* مرتب‌سازی زمانی
* Pagination
* دریافت Tick/Event
* دریافت Market Data
* حفظ Timestamp اصلی داده

### 6.2 Live Data

SDK باید بتواند داده‌های Real-Time را دریافت کند.

رفتار مورد انتظار:

```text
New Market Event
       ↓
Data Provider
       ↓
Event Dispatcher
       ↓
Strategy
```

Strategy باید با دریافت هر Event قابل‌پردازش اجرا شود.

---

## 7. Market Data

Market Data باید حداقل قابلیت نگهداری اطلاعات زیر را داشته باشد:

```text
Symbol
Timestamp
Price
Volume
Bid
Ask
```

در صورت وجود Order Book:

```text
Bids
Asks
Depth
```

همچنین سیستم باید امکان توسعه Market Data برای داده‌هایی مانند موارد زیر را داشته باشد:

* NAV
* Gold Price
* Dollar Price
* Ounce Price
* Coin Price
* Fund Metrics
* سایر داده‌های مورد نیاز Strategy

---

## 8. Data Quality

SDK باید بتواند وضعیت کیفیت داده را مدیریت کند.

موارد مورد توجه:

* Missing Data
* Duplicate Data
* Out-of-Order Data
* Delayed Data
* Stale Data
* Invalid Data
* Timestamp inconsistency

هر Market Event باید امکان نگهداری Timestampهای مرتبط را داشته باشد.

برای مثال:

```text
exchange_timestamp
received_timestamp
processed_timestamp
```

در صورت امکان:

```text
strategy_timestamp
execution_timestamp
```

نیز ثبت شود.

---

## 9. Strategy Requirements

Strategy باید بتواند:

* Market Data دریافت کند
* وضعیت Portfolio را مشاهده کند
* Positionها را مشاهده کند
* Order ایجاد کند
* وضعیت Orderها را مشاهده کند
* Signal ایجاد کند
* Opportunity ایجاد و ثبت کند
* Configuration داشته باشد

Strategy نباید مستقیماً با:

* PostgreSQL
* Celery
* HTTP API
* Redis
* Execution Broker

کار کند.

این مسئولیت‌ها باید در Infrastructure/Engine قرار داشته باشند.

---

## 10. Order Management

SDK باید مفهوم Order را به صورت مستقل مدل کند.

هر Order حداقل باید شامل موارد زیر باشد:

```text
Order ID
Symbol
Side
Quantity
Order Type
Price
Timestamp
Status
Filled Quantity
Remaining Quantity
Average Fill Price
Fees
```

Order Statusهای اصلی:

```text
CREATED
SUBMITTED
PARTIALLY_FILLED
FILLED
CANCELLED
REJECTED
EXPIRED
```

نگاشت نسخه فعلی SDK: `OPEN` ≡ `SUBMITTED`. `CREATED` و `EXPIRED` در P1 اضافه می‌شوند.

---

## 11. Order Types

سیستم باید حداقل از موارد زیر پشتیبانی کند:

### Market Order

```text
BUY / SELL
```

### Limit Order

```text
BUY @ price
SELL @ price
```

در آینده امکان افزودن Order Typeهای دیگر باید وجود داشته باشد.

---

## 12. Execution Simulation

Execution Simulator باید بتواند در چند سطح عمل کند.

### Level 1 — Simple Fill

ساده‌ترین حالت:

```text
Order
 ↓
Current Market Price
 ↓
Fill
```

### Level 2 — Bid / Ask

برای Market Order:

```text
BUY  → Ask
SELL → Bid
```

و برای Limit Order:

```text
BUY  → Ask <= Limit Price
SELL → Bid >= Limit Price
```

### Level 3 — Order Book Simulation

در صورت وجود Order Book، Simulator باید بتواند عمق را walk کند و Average Fill Price را محاسبه کند. این سطح در P1 است.

---

## 13. Partial Fill

سیستم باید Partial Fill را پشتیبانی کند.

مثلاً:

```text
Requested: 1000

Fill #1: 300
Fill #2: 400
Fill #3: 300

Total: 1000
```

هر Fill باید به صورت مستقل ثبت شود.

---

## 14. Slippage Model

SDK باید Slippage را قابل تنظیم کند.

حداقل مدل‌های مورد انتظار:

### Fixed Slippage

```text
price + fixed_amount
```

### Percentage Slippage

```text
price × percentage
```

### Market-Based Slippage

Slippage بر اساس Bid/Ask، Order Book، Order Size و Market Liquidity محاسبه شود (P1).

---

## 15. Fee Model

کارمزد نباید داخل Strategy محاسبه شود.

SDK باید Fee Model مستقل داشته باشد.

Fee Model باید بتواند بر اساس Symbol، Side، Order Type، Quantity و Trade Value کارمزد را محاسبه کند.

خروجی:

```text
Gross Trade Value
Fee
Net Trade Value
```

مدل کارمزد باید قابل جایگزینی و Configuration باشد.

---

## 16. Latency Model

SDK باید امکان شبیه‌سازی Latency داشته باشد.

حداقل latencyهای مورد نظر:

```text
Market Data Latency
Strategy Processing Latency
Order Submission Latency
Execution Latency
```

Latency باید قابل Configuration باشد.

در آینده امکان مدل‌های Fixed، Random و Distribution-Based وجود داشته باشد. P0 فقط `NoLatency` و `FixedLatency` را پیاده می‌کند.

---

## 17. Portfolio Management

SDK باید Portfolio Simulator داشته باشد.

Portfolio شامل:

```text
Cash
Positions
Orders
Trades
Portfolio Value
```

باشد.

برای هر Symbol باید Position قابل محاسبه باشد.

مثلاً:

```text
Fund A
Quantity: 1000
Average Price: 105
Current Price: 110
Unrealized PnL: +5000
```

---

## 18. PnL

سیستم باید حداقل موارد زیر را محاسبه کند:

### Realized PnL

سود و زیان Positionهای بسته‌شده.

### Unrealized PnL

سود و زیان Positionهای باز.

### Total PnL

```text
Realized PnL
+
Unrealized PnL
-
Fees
```

همچنین باید PnL در طول زمان قابل مشاهده باشد.

---

## 19. Arbitrage Opportunity

از آنجا که هدف اصلی SDK توسعه Strategyهای Arbitrage است، مفهوم Opportunity باید در Domain سیستم وجود داشته باشد.

یک Opportunity حداقل باید شامل:

```text
Opportunity ID
Timestamp
Strategy
Symbols
Expected Spread
Expected Profit
Detected At
Expired At
Status
```

Statusهای پیشنهادی:

```text
DETECTED
SIGNAL_GENERATED
ORDER_SUBMITTED
PARTIALLY_CAPTURED
CAPTURED
MISSED
EXPIRED
```

Opportunity tracking در P1 است؛ Signal در P0 به‌صورت event لاگ می‌شود.

---

## 20. Opportunity Lifecycle

چرخه یک Opportunity:

```text
Market Condition
       ↓
Opportunity Detected
       ↓
Strategy Signal
       ↓
Order Created
       ↓
Order Executed
       ↓
Position
       ↓
Exit
       ↓
Realized PnL
```

سیستم باید بتواند مشخص کند چه تعداد Opportunity وجود داشت و Strategy چه تعداد از آن‌ها را واقعاً Capture کرد.

---

## 21. Backtest Metrics

حداقل Metrics عمومی:

```text
Total Return
Total PnL
Realized PnL
Unrealized PnL
Maximum Drawdown
Sharpe Ratio
Win Rate
Number of Trades
Average Trade PnL
```

P0: Total Return، Total/Realized/Unrealized PnL، Maximum Drawdown، Number of Trades، Fill Rate، Total Fees.

---

## 22. Arbitrage Metrics

Metrics تخصصی‌تر (P1):

```text
Total Opportunities
Detected Opportunities
Captured Opportunities
Missed Opportunities
Expired Opportunities
Capture Rate
Average Opportunity Spread
Average Opportunity Duration
Average Expected Profit
Average Realized Profit
Opportunity-to-Trade Conversion Rate
```

---

## 23. Execution Metrics

```text
Total Orders
Filled Orders
Partial Fills
Rejected Orders
Cancelled Orders
Fill Rate
Average Slippage
Total Fees
Average Execution Latency
```

---

## 24. Strategy Metrics

برای هر Strategy:

```text
Total Signals
BUY Signals
SELL Signals
Trades
PnL
Win Rate
Average Holding Time
Opportunities Detected
Opportunities Captured
```

---

## 25. Reproducibility

هر Backtest باید قابل Reproduce باشد.

برای هر اجرای Backtest باید Configuration ذخیره شود:

```text
Backtest ID
Strategy Version
Strategy Configuration
Data Range
Data Version
Initial Capital
Fee Model
Fee Configuration
Slippage Model
Slippage Configuration
Latency Model
Execution Model
Random Seed
```

در صورت اجرای مجدد با همان Configuration و Data، نتیجه باید تا حد امکان deterministic باشد.

P0 این را به‌صورت `RunConfig` ذخیره می‌کند. مقایسه Experiment در P1 است.

---

## 26. Experiment Management

SDK باید امکان اجرای Experimentهای مختلف را فراهم کند. نتیجه باید قابل ذخیره و مقایسه باشد. این قابلیت در P1 تکمیل می‌شود.

---

## 27. Parameter Optimization

در آینده SDK باید امکان اجرای Strategy با Configurationهای مختلف را داشته باشد.

این قابلیت فعلاً جزء **Future Requirement** است ولی API اولیه نباید مانع توسعه آن شود.

---

## 28. Reporting

پس از اجرای Backtest یا Simulation، SDK باید بتواند یک گزارش تولید کند.

گزارش باید شامل Summary، Performance، PnL، Trades، Orders، Execution، Fees، Slippage، Latency، Opportunities، Drawdown باشد.

همچنین امکان دسترسی programmatic به نتایج باید وجود داشته باشد (`RunResult`).

---

## 29. Live Simulation Monitoring

Live Simulation باید امکان مشاهده وضعیت فعلی را داشته باشد.

مثلاً:

```text
Current Cash
Current Positions
Open Orders
Today's PnL
Total PnL
Detected Opportunities
Captured Opportunities
Current Exposure
```

همچنین Eventهای مهم باید قابل مشاهده و Logging باشند.

---

## 30. Separation of Concerns

مسئولیت‌ها باید از یکدیگر جدا باشند.

### Strategy

مسئول Decision Making.

### Data Provider

مسئول Providing Market Data.

### Execution Engine

مسئول Order Execution.

### Portfolio

مسئول Positions / Cash / PnL.

### Fee Model

مسئول Fees.

### Slippage Model

مسئول Slippage.

### Latency Model

مسئول Latency.

### Engine

مسئول Orchestration.

---

## 31. عدم وابستگی Strategy به Backend

Strategy نباید مستقیماً به معماری `goldarb` وابسته باشد.

Strategy نباید چیزی مانند `requests.get(...)` یا `PostgresRepository(...)` انجام دهد.

Strategy باید فقط با abstractionهای SDK کار کند.

این موضوع باعث می‌شود Data Provider در آینده بتواند از goldarb API، Parquet، Database، Kafka، WebSocket یا Live Broker استفاده کند بدون اینکه Strategy تغییر کند.

---

## 32. Error Handling

سیستم باید خطاهای زیر را مدیریت کند:

```text
Data unavailable
Data timeout
Invalid market data
Stale market data
Order rejected
Insufficient cash
Insufficient position
Invalid order
Execution failure
API failure
```

خطا در یک Event نباید الزاماً باعث توقف کل Simulation شود؛ رفتار باید Configuration-based باشد.

---

## 33. Logging و Auditability

تمام رویدادهای مهم باید قابل ثبت باشند.

حداقل:

```text
Market Event
Signal
Opportunity
Order
Fill
Position Change
Fee
PnL Change
Error
```

باید بتوان مسیر زیر را برای یک معامله بازسازی کرد:

```text
Market Event
    ↓
Opportunity
    ↓
Signal
    ↓
Order
    ↓
Fill
    ↓
Position
    ↓
PnL
```

---

## 34. Performance Requirements

SDK باید بتواند حجم قابل توجهی از Market Eventها را پردازش کند.

Backtest نباید الزاماً به سرعت Real-Time محدود باشد.

Performance به‌خصوص در Data Processing و Event Dispatching باید قابل اندازه‌گیری باشد.

---

## 35. Extensibility

سیستم باید قابلیت توسعه موارد زیر را داشته باشد:

```text
New Strategy
New Data Provider
New Execution Model
New Broker
New Fee Model
New Slippage Model
New Latency Model
New Metric
New Report
New Order Type
```

بدون تغییرات گسترده در Core سیستم.

---

## 36. تست‌پذیری

هر بخش مهم SDK باید Unit Test داشته باشد.

حداقل:

```text
Strategy Tests
Data Provider Tests
Order Tests
Execution Tests
Fee Tests
Slippage Tests
Latency Tests
Portfolio Tests
PnL Tests
Backtest Engine Tests
```

همچنین باید Integration Test برای ارتباط با API پروژه `goldarb` وجود داشته باشد.

---

## 37. Non-Functional Requirements

## Reliability

خطاهای Data Provider یا یک Order نباید بدون کنترل باعث از دست رفتن وضعیت Simulation شوند.

## Determinism

Backtestهای مشابه باید نتایج قابل تکرار باشند.

## Observability

تمام مراحل مهم Strategy → Order → Execution → PnL باید قابل مشاهده باشند.

## Extensibility

اضافه‌کردن Strategy و Model جدید نباید نیازمند تغییر Core باشد.

## Usability

تیم Trading باید بتواند بدون درگیرشدن با جزئیات Infrastructure یک Strategy را اجرا کند.

---

## 38. اولویت‌بندی Requirements

### P0 — ضروری برای نسخه اول

```text
Historical Data
Live Data
Strategy API
Backtest Engine
Live Simulation Engine
Order Model
Order Execution
Portfolio
PnL
Fee Model
Bid/Ask Execution
Basic Slippage
Basic Latency
Basic Metrics
Logging
```

### P1 — ضروری برای نسخه حرفه‌ای

```text
Order Book Execution
Partial Fill
Advanced Slippage
Advanced Latency
Opportunity Tracking
Execution Metrics
Experiment Management
Reproducibility
Detailed Reporting
Data Quality Detection
```

### P2 — Future

```text
Parameter Optimization
Strategy Comparison
Advanced Analytics
Live Broker Integration
Live Trading
Multi-Broker
Distributed Backtesting
```

---

## 39. سناریوی اصلی سیستم

سناریوی مورد انتظار برای Strategy حباب صندوق‌ها:

```text
             Market Data
                  │
                  ▼
             Data Provider
                  │
                  ▼
             Market Event
                  │
                  ▼
              Strategy
                  │
            Bubble Calculation
                  │
                  ▼
          Arbitrage Opportunity
                  │
                  ▼
                Signal
                  │
                  ▼
               Order
                  │
                  ▼
          Execution Simulator
                  │
          ┌───────┴────────┐
          ▼                ▼
       Partial           Fill
        Fill
          │
          └───────┬────────┘
                  ▼
              Portfolio
                  │
          ┌───────┴────────┐
          ▼                ▼
        Position           Cash
                  │
                  ▼
                 PnL
                  │
                  ▼
               Metrics
```

همین جریان باید بتواند با Historical Data و Live Data اجرا شود.

---

## 40. معیار موفقیت پروژه

`goldarb-lab` زمانی نیازمندی‌های اصلی خود را برآورده کرده است که:

1. Trader بتواند یک Strategy بنویسد.
2. همان Strategy بدون تغییر اساسی روی Historical Data اجرا شود.
3. همان Strategy بدون تغییر اساسی روی Live Data اجرا شود.
4. Orderها به‌صورت واقع‌گرایانه شبیه‌سازی شوند.
5. Fee، Slippage و Latency در نتایج لحاظ شوند.
6. Portfolio و PnL به‌صورت دقیق محاسبه شوند.
7. Opportunityهای Arbitrage قابل ردیابی باشند.
8. مشخص باشد Strategy چه Opportunityهایی را دیده و چه تعداد را Capture کرده است.
9. نتیجه Backtest قابل Reproduce باشد.
10. در آینده بتوان Execution Simulator را با Real Broker جایگزین کرد بدون اینکه Strategy تغییر اساسی کند.

---

## 41. خارج از محدوده نسخه اولیه

موارد زیر فعلاً در Scope نسخه اولیه نیستند:

* ارسال سفارش واقعی
* مدیریت حساب واقعی Broker
* Multi-Exchange Order Routing
* Machine Learning Pipeline
* Distributed Backtesting
* Parameter Optimization پیشرفته
* UI کامل برای تحلیل Backtest

این موارد باید در معماری آینده قابل اضافه‌شدن باشند ولی نباید پیچیدگی غیرضروری به MVP اضافه کنند.

---

## 42. تصمیمات معماری که بعد از تأیید Requirements باید گرفته شوند

پس از تأیید این سند، مرحله بعد باید شامل تصمیم‌گیری درباره موارد زیر باشد:

1. Domain Model
2. Event Model
3. Strategy Interface
4. Data Provider Interface
5. Execution Interface
6. Order Model
7. Fill Model
8. Portfolio Model
9. Fee Model
10. Slippage Model
11. Latency Model
12. Backtest Engine
13. Live Simulation Engine
14. Broker Interface
15. Result / Metrics Model
16. Experiment Model
17. Repository Structure
18. Sync/Async Model
19. API Client Architecture
20. Testing Architecture

پیاده‌سازی P0 این نسخه این تصمیم‌ها را در کد قفل می‌کند. جزئیات در ماژول‌های `goldarb.strategy`، `goldarb.data`، `goldarb.execution` و `goldarb.engine`.

---

## 43. اصل نهایی طراحی

اصل محوری `goldarb-lab` این است:

> **Write Strategy Once, Run It Everywhere.**

یعنی Trader باید بتواند یک Strategy را توسعه دهد و همان Strategy را در محیط‌های زیر اجرا کند:

```text
              ┌──────────────┐
              │   Strategy   │
              └───────┬──────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      Backtest    Simulation   Live Trading
```

و تفاوت این محیط‌ها باید عمدتاً در:

```text
Data Source
Execution Model
```

باشد، نه در منطق Strategy.
