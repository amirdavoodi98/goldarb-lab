"""Offline parsing: aliases, unknown times, timezone conversion and JSON export."""

import json
from datetime import UTC

from goldarb.session import TEHRAN, snapshot_from_live, source_read_timestamp
from goldarb.simulation.models import jsonable

from _price_timestamp_demo import DEMO_NOW


def main():
    cases = {
        "UTC with microseconds": {"fetched_at": "2026-08-29T09:30:00.123456Z"},
        "Tehran offset": {"fetched_at": "2026-08-29T13:00:00.123456+03:30"},
        "legacy alias": {"last_update": "2026-08-29T09:30:00.123456+00:00"},
        "primary wins": {"fetched_at": DEMO_NOW.isoformat(),
                         "last_update": "2026-08-28T09:30:00Z"},
        "missing": {},
        "null": {"fetched_at": None},
        "invalid": {"fetched_at": "bad"},
        "timezone missing": {"fetched_at": "2026-08-29T13:00:00"},
        "trade time only": {"d_even": "20260829", "h_even": "130000"},
        "as_of only": {"as_of": DEMO_NOW.isoformat()},
    }
    for name, payload in cases.items():
        stamp = source_read_timestamp(payload)
        print(f"{name}: {stamp}")
        if stamp is not None:
            print("  UTC:", stamp.astimezone(UTC), "Tehran:", stamp.astimezone(TEHRAN))
    snapshot = snapshot_from_live(
        symbol="طلا", last_price={"last_price": "100", **cases["UTC with microseconds"]},
        now=DEMO_NOW,
    )
    print("JSON export (ISO timestamp survives):")
    print(json.dumps(jsonable(snapshot), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
