#!/usr/bin/env python3
"""Read-only SDK delivery probe; credentials come from GOLDARB_* environment."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from statistics import median

from goldarb import LabClient


def distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "min": round(ordered[0], 3),
        "p50": round(median(ordered), 3),
        "p95": round(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)], 3),
        "max": round(ordered[-1], 3),
    }


def probe(client: LabClient, *, source: str, symbols: list[str], duration: float) -> dict:
    snapshot = client.live.snapshot(
        source=source, symbols=symbols, require_verified_source_time=False
    )
    cursor = snapshot["cursor"]
    start = time.monotonic()
    samples = {
        "receipt_to_stream_ms": [],
        "stream_to_sdk_ms": [],
        "receipt_to_sdk_ms": [],
        "unverified_source_candidate_age_ms": [],
    }
    statuses, seen = {}, set()
    batches = 0
    while time.monotonic() - start < duration:
        batch = client.live.events(
            source=source,
            symbols=symbols,
            cursor=cursor,
            require_verified_source_time=False,
            block_ms=1000,
            limit=500,
        )
        observed = datetime.now(UTC).timestamp() * 1000
        batches += 1
        for item in batch["events"]:
            event = item["event"]
            received = datetime.fromisoformat(event["received_at"]).timestamp() * 1000
            committed = int(item["cursor"].split("-")[0])
            samples["receipt_to_stream_ms"].append(committed - received)
            samples["stream_to_sdk_ms"].append(observed - committed)
            samples["receipt_to_sdk_ms"].append(observed - received)
            candidate = event.get("source_time_candidate")
            if candidate:
                samples["unverified_source_candidate_age_ms"].append(
                    observed - datetime.fromisoformat(candidate).timestamp() * 1000
                )
            status = event["source_time_status"]
            statuses[status] = statuses.get(status, 0) + 1
            seen.add(event["symbol"])
        # A checkpoint follows processing of the complete batch, including filtered rows.
        cursor = batch["cursor"]
    return {
        "source": source,
        "observed_at": datetime.now(UTC).isoformat(),
        "duration_seconds": round(time.monotonic() - start, 3),
        "batches": batches,
        "symbols_observed": sorted(seen),
        "initial_snapshot_count": len(snapshot["observations"]),
        "source_time_statuses": statuses,
        "milliseconds": {name: distribution(values) for name, values in samples.items()},
        "limitations": [
            "Candidate source age is not verified source latency.",
            "Receipt/Redis/SDK wall-clock deltas require synchronized clocks.",
            "This measures delivery age during this sample, not a full market session.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["mofid", "tsetmc"], default="mofid")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--duration", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.duration <= 300:
        parser.error("duration must be >0 and <=300 seconds")
    try:
        with LabClient.from_env() as client:
            result = probe(client, source=args.source, symbols=args.symbols, duration=args.duration)
    except Exception as exc:  # noqa: BLE001 - sanitize authenticated transport errors at CLI boundary
        # Never include authenticated URLs/headers or vendor response bodies.
        parser.exit(1, "SDK probe failed: " + type(exc).__name__ + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
