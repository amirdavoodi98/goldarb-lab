"""Bulk API prices: inspect and gate each symbol independently. Optional --live."""

import argparse
from datetime import UTC, datetime

from goldarb.session import source_read_timestamp

from _price_timestamp_demo import DEMO_NOW, example_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-age", type=float, default=3.0)
    args = parser.parse_args()
    if args.max_age < 0:
        parser.error("--max-age must be nonnegative")
    with example_client(args.live) as client:
        payload = client.fund.last_prices()
    now = datetime.now(UTC) if args.live else DEMO_NOW
    # The platform bulk endpoint returns {"funds": [...]}; no batch-wide read time.
    for row in payload["funds"]:
        stamp = source_read_timestamp(row)
        age = None if stamp is None else (now - stamp).total_seconds()
        usable = (
            row.get("last_price") is not None
            and row.get("status") not in {"stale", "unavailable"}
            and age is not None and 0 <= age <= args.max_age
        )
        print(f"{row['symbol']}: price={row.get('last_price')}, read={stamp}, "
              f"age={age}s -> {'USE' if usable else 'SKIP'}")


if __name__ == "__main__":
    main()
