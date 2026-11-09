import httpx
import pytest
import respx

from goldarb import LabClient


@respx.mock
def test_snapshot_strict_default_and_token():
    def handle(request):
        assert request.headers["Authorization"] == "Token test-token"
        assert request.url.params["require_verified_source_time"] == "true"
        assert request.url.params["symbols"] == "طلا,عیار"
        return httpx.Response(200, json={"schema_version": 1, "delivery": "snapshot_only"})

    respx.get("https://example.test/api/v1/lab/market-data/snapshot/").mock(side_effect=handle)
    with LabClient(base_url="https://example.test", token="test-token") as client:
        assert client.live.snapshot(symbols=["طلا", "عیار"])["delivery"] == "snapshot_only"


@respx.mock
def test_diagnostic_mode_and_bad_schema():
    route = respx.get("https://example.test/api/v1/lab/market-data/snapshot/").mock(
        return_value=httpx.Response(200, json={"schema_version": 1})
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        client.live.snapshot(require_verified_source_time=False)
        assert route.calls[0].request.url.params["require_verified_source_time"] == "false"
        route.mock(return_value=httpx.Response(200, json={"schema_version": 2}))
        with pytest.raises(ValueError, match="schema"):
            client.live.snapshot()
        with pytest.raises(ValueError, match="tsetmc"):
            client.live.snapshot(source="unknown")
        with pytest.raises(ValueError, match="symbols"):
            client.live.snapshot(symbols=[])


@respx.mock
def test_mofid_uses_same_authenticated_lab_contract():
    route = respx.get("https://example.test/api/v1/lab/market-data/snapshot/").mock(
        return_value=httpx.Response(200, json={"schema_version": 1, "source": "mofid"})
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        assert client.live.snapshot(source="mofid", symbols=["گلدیس"])["source"] == "mofid"
    assert route.calls[0].request.url.params["source"] == "mofid"
    assert route.calls[0].request.headers["Authorization"] == "Token test-token"


@respx.mock
def test_long_poll_batches_resume_after_processing():
    route = respx.get("https://example.test/api/v1/lab/market-data/events/").mock(
        return_value=httpx.Response(200, json={"schema_version": 1, "cursor": "10-0", "events": []})
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        subscription = client.live.subscribe(cursor="0-0", symbols=["گلدیس"])
        assert next(subscription)["cursor"] == "10-0"
        next(subscription)
        assert route.calls[0].request.url.params["cursor"] == "0-0"
        assert route.calls[1].request.url.params["cursor"] == "10-0"
        subscription.close()
        route.mock(return_value=httpx.Response(409, json={"detail": "cursor_gap"}))
        with pytest.raises(httpx.HTTPStatusError):
            client.live.events(cursor="1-0")


@respx.mock
def test_provider_timestamp_reaches_sdk_without_becoming_verified_trade_time():
    event = {
        "source": "mofid",
        "symbol": "گلدیس",
        "payload": {"last_price": "48929"},
        "source_timestamp": "2026-11-01T12:41:39+00:00",
        "received_at": "2026-11-01T12:41:40+00:00",
        "source_event_time": None,
        "source_time_status": "unverified",
    }
    respx.get("https://example.test/api/v1/lab/market-data/snapshot/").mock(
        return_value=httpx.Response(200, json={"schema_version": 1, "observations": [event]})
    )
    respx.get("https://example.test/api/v1/lab/market-data/events/").mock(
        return_value=httpx.Response(
            200,
            json={
                "schema_version": 1,
                "cursor": "10-0",
                "events": [{"cursor": "10-0", "event": event}],
            },
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        snapshot = client.live.snapshot(source="mofid", require_verified_source_time=False)
        batch = client.live.events(source="mofid", cursor="0-0", require_verified_source_time=False)
    assert snapshot["observations"][0] == event
    assert batch["events"][0]["event"] == event
    assert event["source_timestamp"] != event["received_at"]


def test_package_and_release_metadata_versions_agree():
    import tomllib
    from pathlib import Path

    import goldarb

    metadata = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert goldarb.__version__ == metadata["project"]["version"]


@respx.mock
def test_agah_authenticated_snapshot_and_events_preserve_source_clock():
    event = {
        "source": "agah",
        "source_timestamp": "2026-11-02T10:30:00+00:00",
        "source_event_time": None,
        "source_time_status": "unverified",
    }
    snapshot = respx.get("https://example.test/api/v1/lab/market-data/snapshot/").respond(
        200, json={"schema_version": 1, "observations": [event], "cursor": "1-0"}
    )
    events = respx.get("https://example.test/api/v1/lab/market-data/events/").respond(
        200,
        json={"schema_version": 1, "events": [{"cursor": "2-0", "event": event}], "cursor": "2-0"},
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        assert client.live.snapshot(source="agah", require_verified_source_time=False)[
            "observations"
        ] == [event]
        assert (
            client.live.events(source="agah", cursor="1-0", block_ms=0)["events"][0]["event"]
            == event
        )
    assert snapshot.calls[0].request.url.params["source"] == "agah"
    assert events.calls[0].request.url.params["source"] == "agah"
    assert events.calls[0].request.headers["Authorization"] == "Token test-token"
