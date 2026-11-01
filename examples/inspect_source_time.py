"""Read pilot evidence explicitly; this is a snapshot, not a live subscription."""

import argparse

from goldarb import LabClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["tsetmc", "mofid"], default="tsetmc")
    args = parser.parse_args()
    with LabClient.from_env() as client:
        snapshot = client.live.snapshot(
            source=args.source, symbols=["طلا", "عیار", "گلدیس"], require_verified_source_time=False
        )
        print("delivery:", snapshot["delivery"], "durable:", snapshot["durable"])
        for event in snapshot["observations"]:
            print(
                event["symbol"],
                event["payload"]["last_price"],
                "source_timestamp:",
                event["source_timestamp"],
                "verified_trade_time:",
                event["source_event_time"],
                "raw_clock:",
                event["source_time_raw"],
                "status:",
                event["source_time_status"],
                "received_at:",
                event["received_at"],
            )
        for excluded in snapshot["excluded"]:
            print("excluded:", excluded["symbol"], excluded["reason"])


if __name__ == "__main__":
    main()
