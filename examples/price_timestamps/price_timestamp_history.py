"""Offline history: bar time differs from acquisition time; forward fill keeps age."""

from datetime import timedelta

from goldarb.data import snapshots_from_bars, snapshots_from_symbol_bars

from _price_timestamp_demo import DEMO_NOW, show_quote


def main():
    start = DEMO_NOW.replace(microsecond=0)
    acquired = start - timedelta(seconds=1, microseconds=123456)
    bars = [
        {"bar_at": start.isoformat(), "close": "100", "fetched_at": acquired.isoformat()},
        # Historical bars often have no acquisition metadata. Do not use bar_at for it.
        {"bar_at": (start + timedelta(seconds=2)).isoformat(), "close": "101"},
    ]
    print("Individual bars:")
    for snapshot in snapshots_from_bars(bars, symbol="طلا"):
        print("Bar time:", snapshot.timestamp)
        show_quote(snapshot.quotes[0], snapshot.timestamp)
    print("Aligned 1-second grid (the middle quote is forward filled):")
    for snapshot in snapshots_from_symbol_bars({"طلا": bars}):
        print("Grid time:", snapshot.timestamp)
        show_quote(snapshot.quotes[0], snapshot.timestamp)


if __name__ == "__main__":
    main()
