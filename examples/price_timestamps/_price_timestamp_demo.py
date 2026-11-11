"""Shared offline fixtures for the price timestamp examples; no network by default."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

from goldarb import LabClient
from goldarb._http import LabHttp
from goldarb.session import TEHRAN

# A Saturday inside the Tehran trading session, so offline polling always works.
DEMO_NOW = datetime(2026, 8, 29, 13, 0, 0, 654321, tzinfo=TEHRAN)


def demo_response(path, params=None):
    del params
    path = unquote(path)
    prices = [
        {"symbol": "طلا", "last_price": "100", "status": "ok",
         "d_even": "20260829", "h_even": "125925",
         "fetched_at": (DEMO_NOW - timedelta(seconds=1)).isoformat()},
        # Deliberately old: the example's own freshness rule must reject this.
        {"symbol": "عیار", "last_price": "200", "status": "ok",
         "d_even": "20260829", "h_even": "125400",
         "fetched_at": (DEMO_NOW - timedelta(minutes=5)).isoformat()},
    ]
    books = [
        {"symbol": row["symbol"], "best_bid": "99", "best_ask": "101",
         "fetched_at": (DEMO_NOW - timedelta(milliseconds=500)).isoformat()}
        for row in prices
    ]
    if path == "/api/v1/funds/last-price/":
        return deepcopy({"funds": prices})
    if path == "/api/v1/funds/orderbook/":
        return deepcopy({"funds": books})
    if path == "/api/v1/funds/nav/live/":
        return {"funds": [{"symbol": row["symbol"], "nav": "99",
                           "fetched_at": DEMO_NOW.isoformat()} for row in prices]}
    for rows, suffix in ((prices, "last-price"), (books, "orderbook")):
        for row in rows:
            if path == f"/api/v1/funds/{row['symbol']}/{suffix}/":
                return deepcopy(row)
    raise ValueError(f"Unexpected demo endpoint: {path}")


@contextmanager
def example_client(live=False):
    if live:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        with LabClient.from_env() as client:
            yield client
    else:
        # Replace only transport responses; run the real SDK conversion code.
        print("OFFLINE DEMO (fixed source data; no API credentials needed)")
        with patch.object(LabHttp, "get_json", side_effect=demo_response):
            with LabClient(base_url="https://example.test", token="demo") as client:
                yield client


def show_quote(quote, now):
    age = None if quote.fetched_at is None else (now - quote.fetched_at).total_seconds()
    age_text = "unknown" if age is None else f"{age:.6f}s"
    print(f"{quote.symbol}: last={quote.last}, fetched_at={quote.fetched_at}, age={age_text}")
    print(f"  source_timestamp={quote.source_timestamp}, status={quote.source_time_status}")
    print(f"  bid={quote.bid}, ask={quote.ask}, book read={quote.orderbook_fetched_at}")
