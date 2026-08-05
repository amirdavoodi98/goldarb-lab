#!/usr/bin/env python3
"""Fetch: قیمت تتر نوبیتکس (USDT/IRT live tip, unit=toman)."""

try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import get_usdt_live
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import get_usdt_live


def main() -> None:
    client = get_client()
    try:
        data = get_usdt_live(client)
        print(data)
    finally:
        close_client()


if __name__ == "__main__":
    main()
