"""Offline book scenarios: independent timestamps, midpoint and single-sided book."""

from datetime import timedelta

from goldarb.data import normalize_quote
from goldarb.session import snapshot_from_live

from _price_timestamp_demo import DEMO_NOW, show_quote


def main():
    price = {"last_price": "100", "fetched_at": (DEMO_NOW - timedelta(seconds=2)).isoformat()}
    book = {"best_bid": "98", "best_ask": "104",
            "fetched_at": (DEMO_NOW - timedelta(milliseconds=500)).isoformat()}
    cases = [
        ("Last and book have independent read times", price, book),
        ("Missing last: midpoint inherits book time", {}, book),
        ("Stale last: midpoint inherits book time", {**price, "status": "stale"}, book),
        ("Unknown last time stays unknown despite a fresh book", {"last_price": "100"}, book),
        ("Midpoint with unknown book time", {}, {"best_bid": "98", "best_ask": "104"}),
        ("Bid only: no last time", {}, {"best_bid": "98", "fetched_at": book["fetched_at"]}),
        ("No usable data", {}, {}),
    ]
    for name, last, depth in cases:
        print(name)
        snapshot = snapshot_from_live(symbol="طلا", last_price=last, orderbook=depth, now=DEMO_NOW)
        if snapshot is None:
            print("  No snapshot")
            continue
        show_quote(snapshot.quotes[0], DEMO_NOW)
    snapshot = snapshot_from_live(symbol="طلا", last_price=price, orderbook=book, now=DEMO_NOW)
    print("quote_fill modes preserve timestamps while shaping bid/ask:")
    for mode in ("last", "book"):
        print(mode)
        show_quote(normalize_quote(snapshot.quotes[0], mode), DEMO_NOW)


if __name__ == "__main__":
    main()
