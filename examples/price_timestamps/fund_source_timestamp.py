"""Print both clocks from client.fund; offline by default, optional --live."""

import argparse

from _price_timestamp_demo import example_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--symbol", default="طلا")
    args = parser.parse_args()
    with example_client(args.live) as client:
        price = client.fund.last_price(args.symbol)
        print("symbol:", price.get("symbol", args.symbol))
        print("price:", price.get("last_price"))
        print("source_timestamp (source clock):", price["source_timestamp"])
        print("fetched_at (collector read clock):", price.get("fetched_at"))
        print("source_time_status:", price["source_time_status"])
        print("Bulk prices:")
        for row in client.fund.last_prices()["funds"]:
            print(row["symbol"], "price:", row.get("last_price"),
                  "source:", row["source_timestamp"], "read:", row.get("fetched_at"),
                  "status:", row["source_time_status"])


if __name__ == "__main__":
    main()
