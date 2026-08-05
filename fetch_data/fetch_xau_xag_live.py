#!/usr/bin/env python3
"""Fetch: قیمت انس جهانی طلا و نقره (global XAU/XAG spot, live tip)."""

try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import get_xau_xag_live
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import get_xau_xag_live


def main() -> None:
    client = get_client()
    try:
        data = get_xau_xag_live(client)
        print(data)
    finally:
        close_client()


if __name__ == "__main__":
    main()
