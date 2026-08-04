#!/usr/bin/env python3
"""Fetch: قیمت شمش طلا (IME CDC GoldBar, live orderbook + last price)."""

try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import get_gold_bar_live
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import get_gold_bar_live


def main() -> None:
    client = get_client()
    try:
        data = get_gold_bar_live(client)
        print(data)
    finally:
        close_client()


if __name__ == "__main__":
    main()
