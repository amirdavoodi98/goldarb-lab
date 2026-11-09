"""Single-symbol API response and conversion to a timestamped Quote. Optional --live."""

import argparse
from datetime import UTC, datetime

from goldarb.session import snapshot_from_live

from _price_timestamp_demo import DEMO_NOW, example_client, show_quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--symbol", default="طلا")
    args = parser.parse_args()
    with example_client(args.live) as client:
        payload = client.fund.last_price(args.symbol)
        book = client.fund.orderbook(args.symbol)
    now = datetime.now(UTC) if args.live else DEMO_NOW
    print("Raw price response:", payload)
    snapshot = snapshot_from_live(
        symbol=args.symbol, last_price=payload, orderbook=book, now=now,
    )
    if snapshot is None:
        print("No usable price or book. A status='stale' last price is suppressed by the SDK.")
        return
    show_quote(snapshot.quotes[0], now)


if __name__ == "__main__":
    main()
