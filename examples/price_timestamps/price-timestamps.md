# Price source-read timestamps

Run all commands from the repository root. Install once:

```bash
python -m pip install -e .
```

Each example runs independently. By default every example is an **offline demo**:
no credentials, network, trading session or orders are required. The API examples
replace HTTP JSON responses with fixed sample data while using the real SDK.

| Scenario | Command |
| --- | --- |
| Both source and collector clocks from client.fund (single and bulk) | `python examples/price_timestamps/fund_source_timestamp.py` |
| Single-symbol API price and timestamped quote | `python examples/price_timestamps/price_timestamp_single.py` |
| Bulk prices with a separate freshness decision per symbol | `python examples/price_timestamps/price_timestamp_bulk.py` |
| Strategy input: poll time versus source time, repeated prices and NAV | `python examples/price_timestamps/price_timestamp_provider.py` |
| Strategy input with real bid/ask retained (`quote_fill="book"`) | `python examples/price_timestamps/price_timestamp_provider.py --quote-fill book` |
| Fresh, threshold boundary, old, future and unknown timestamps | `python examples/price_timestamps/price_timestamp_freshness.py` |
| Custom freshness threshold | `python examples/price_timestamps/price_timestamp_freshness.py --max-age 1` |
| UTC, Tehran offset, microseconds, legacy alias, missing/invalid timestamps and JSON export | `python examples/price_timestamps/price_timestamp_formats.py` |
| Independent book timestamp, midpoint fallback, single-sided book and no data | `python examples/price_timestamps/price_timestamp_orderbook.py` |
| Historical bars, missing acquisition metadata and forward-filled prices | `python examples/price_timestamps/price_timestamp_history.py` |

In the bulk and provider demos, طلا is fresh and عیار is five minutes old.
The provider's second poll advances the event time without changing source-read
times. The history example shows that a forward-filled price keeps getting older.

## Real API data

For both clocks from the ordinary fund API, run
`python examples/price_timestamps/fund_source_timestamp.py --live`.
`source_timestamp` is independent of `fetched_at`; it is `None` when unknown.
Legacy date/time pairs are marked `source_time_status="unverified"` because
the upstream server may have inferred their date. Explicit server source
timestamps and their verification status take precedence. Strategy quotes
preserve these fields too; an order-book midpoint uses only its own book's
source clock, if available.

The single, bulk and provider examples support `--live`. They load the repository's
`.env` and use `GOLDARB_BASE_URL` and `GOLDARB_TOKEN`. Alternatively, export those
variables in your shell. A missing credential produces an error rather than
silently using demo data.

```bash
python examples/price_timestamps/price_timestamp_single.py --live --symbol طلا
```

```bash
python examples/price_timestamps/price_timestamp_bulk.py --live --max-age 3
```

```bash
python examples/price_timestamps/price_timestamp_provider.py --live
```

```bash
python examples/price_timestamps/price_timestamp_provider.py --live --quote-fill book
```

The provider makes two polls, one second apart. Live provider events are limited
to Saturday–Wednesday, 12:00–18:00 Asia/Tehran. It prints a message if no events
are available. Direct single/bulk API requests can run outside that window, but
source data may be stale or unavailable. Live API requests were not used to
validate these examples.

## What the fields mean

- `Quote.fetched_at`: acquisition time for `last`, parsed as a timezone-aware
  `datetime`. The platform's `last_update` is the legacy alias.
- `Quote.orderbook_fetched_at`: independent acquisition time for bid/ask.
- `MarketSnapshot.timestamp`: polling event time in `LiveDataProvider`. The
  standalone `snapshot_from_live` helper can instead use source/trade time;
  always use quote fields when deciding freshness.
- Missing, invalid and timezone-less source times remain `None`. Trade time
  (`d_even`/`h_even`), `as_of`, NAV time and the current clock cannot establish
  the price's acquisition time.
- The SDK already suppresses last prices marked `status="stale"`. With a
  two-sided book it can create a midpoint; that price inherits the book's read
  time. A midpoint is derived, so inspect the raw response if your analysis
  specifically requires a last-trade price.
- Historical bar time is not acquisition time. Historical quotes get
  `fetched_at` only when the input supplies acquisition metadata.

The freshness policy is an example: require a known, non-future timestamp and
an age within your chosen threshold. A timestamp alone is not a trading signal.
