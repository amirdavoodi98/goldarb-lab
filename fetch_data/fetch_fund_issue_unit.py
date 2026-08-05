#!/usr/bin/env python3
"""
Fetch: تعداد واحدهای صندوق — total outstanding ETF units (fund-wide,
near-daily as-of; NOT a specific investor's position).
"""

import sys

try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import get_fund_issued_units
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import get_fund_issued_units

DEFAULT_SYMBOL = "طلا"


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SYMBOL
    client = get_client()
    try:
        data = get_fund_issued_units(client, symbol)
        print(data)
    finally:
        close_client()


if __name__ == "__main__":
    main()
