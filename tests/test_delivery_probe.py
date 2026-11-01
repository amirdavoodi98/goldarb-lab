import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

spec = importlib.util.spec_from_file_location(
    "delivery_probe", Path(__file__).resolve().parents[1] / "examples/probe_live_delivery.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_distribution_keeps_clock_skew_visible():
    assert module.distribution([]) == {"count": 0}
    result = module.distribution([-2, 1, 3, 4])
    assert result == {"count": 4, "min": -2, "p50": 2.0, "p95": 4, "max": 4}


def test_probe_checkpoints_after_batch_and_labels_unverified_age(monkeypatch):
    clock = iter([0, 0, 2, 2])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    client = MagicMock()
    client.live.snapshot.return_value = {"cursor": "1000-0", "observations": []}
    client.live.events.return_value = {
        "cursor": "2000-0",
        "events": [
            {
                "cursor": "2000-0",
                "event": {
                    "received_at": "1970-01-01T00:00:01+00:00",
                    "source_time_candidate": "1970-01-01T00:00:00+00:00",
                    "source_time_status": "ambiguous",
                    "symbol": "عیار",
                },
            }
        ],
    }
    result = module.probe(client, source="mofid", symbols=["عیار"], duration=1)
    assert result["source_time_statuses"] == {"ambiguous": 1}
    assert result["milliseconds"]["receipt_to_stream_ms"]["p50"] == 1000
    assert result["milliseconds"]["unverified_source_candidate_age_ms"]["count"] == 1
    assert client.live.events.call_args.kwargs["cursor"] == "1000-0"
    assert "source_to_sdk_ms" not in result["milliseconds"]


def test_probe_does_not_hide_transport_failures():
    client = MagicMock()
    client.live.snapshot.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        module.probe(client, source="mofid", symbols=["عیار"], duration=1)
