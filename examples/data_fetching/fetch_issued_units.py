#!/usr/bin/env python3
"""Example: issued / outstanding ETF units via nav_live (near-daily as-of)."""

from goldarb import LabClient


def main() -> None:
    with LabClient.from_env() as client:
        units = client.fund.issued_units("طلا")
        print(units)


if __name__ == "__main__":
    main()
