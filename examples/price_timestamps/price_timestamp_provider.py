"""Strategy input: separate poll time, source-read time and NAV time. Optional --live."""

import argparse
import time
from datetime import UTC, datetime, timedelta

from goldarb.data import LabLiveFeed, LiveDataProvider

from _price_timestamp_demo import DEMO_NOW, example_client, show_quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--quote-fill", choices=("last", "book"), default="last")
    args = parser.parse_args()
    clock = DEMO_NOW
    with example_client(args.live) as client:
        provider = LiveDataProvider(
            LabLiveFeed(client), symbols=("طلا", "عیار"),
            include_session_bars=False, quote_fill=args.quote_fill,
            now=None if args.live else lambda: clock,
        )
        for index in range(2):
            if index:
                if args.live:
                    time.sleep(1)
                else:
                    clock += timedelta(seconds=1)
            events = provider.poll()
            if not events:
                print("No events: check trading session, feed availability and price status.")
            for snapshot in events:
                print("Poll event time:", snapshot.timestamp)
                for quote in snapshot.quotes:
                    # Put this check before your strategy's signal calculation.
                    now = datetime.now(UTC) if args.live else clock
                    show_quote(quote, now)
                    age = (now - quote.fetched_at).total_seconds() if quote.fetched_at else None
                    print("  Signal input:", "USE" if age is not None and 0 <= age <= 3 else "SKIP",
                          "NAV:", quote.nav)
    print("A repeated price keeps its source time; the poll time advances.")
    print("NAV read time never fills a missing price read time.")


if __name__ == "__main__":
    main()
