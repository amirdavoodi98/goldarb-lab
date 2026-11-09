"""Offline freshness policy: fresh, threshold boundary, old, future and unknown."""

import argparse
from datetime import timedelta
from decimal import Decimal

from goldarb.simulation.models import Quote

from _price_timestamp_demo import DEMO_NOW


def freshness_decision(quote, *, now, max_age):
    """Example policy; choose the allowed age to suit your analysis."""
    if quote.last is None:
        return "SKIP: no last price"
    if quote.fetched_at is None:
        return "SKIP: source-read time unknown"
    age = (now - quote.fetched_at).total_seconds()
    if age < 0:
        return "SKIP: timestamp is in the future (check clocks)"
    if age > max_age:
        return f"SKIP: too old ({age:.6f}s)"
    return f"USE: fresh ({age:.6f}s)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age", type=float, default=3.0)
    args = parser.parse_args()
    if args.max_age < 0:
        parser.error("--max-age must be nonnegative")
    cases = {
        "fresh": DEMO_NOW - timedelta(milliseconds=500),
        "at threshold": DEMO_NOW - timedelta(seconds=args.max_age),
        "too old": DEMO_NOW - timedelta(seconds=args.max_age + 1),
        "future": DEMO_NOW + timedelta(seconds=1),
        "unknown": None,
    }
    for name, stamp in cases.items():
        quote = Quote(symbol="طلا", last=Decimal("100"), fetched_at=stamp)
        print(name, "->", freshness_decision(quote, now=DEMO_NOW, max_age=args.max_age))


if __name__ == "__main__":
    main()
