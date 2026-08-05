#!/usr/bin/env python3
"""Fetch: پورتفولیوی صندوق — ترکیب دارایی (asset composition %) for one fund."""

import sys

try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import get_fund_holdings
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import get_fund_holdings

DEFAULT_SYMBOL = "طلا"


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SYMBOL
    client = get_client()
    try:
        data = get_fund_holdings(client, symbol)
        print(data)
    finally:
        close_client()


if __name__ == "__main__":
    main()
