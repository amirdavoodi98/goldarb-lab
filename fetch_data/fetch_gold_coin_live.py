#!/usr/bin/env python3
"""Fetch: قیمت سکه طلا (IME CDC GoldCoin, live orderbook + last price)."""

try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import get_gold_coin_live
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import get_gold_coin_live


def main() -> None:
    client = get_client()
    try:
        data = get_gold_coin_live(client)
        print(data)
    finally:
        close_client()


if __name__ == "__main__":
    main()
