"""Published platform additions coexist with the standalone strategy client."""

import json

import httpx
import pytest
import respx

from goldarb import LabClient


@respx.mock
def test_existing_login_also_initializes_source_aware_and_ml_clients():
    respx.post("https://example.test/api/v1/auth/token/").mock(
        return_value=httpx.Response(200, json={"token": "login-test-token"})
    )
    route = respx.get("https://example.test/api/v1/lab/market-data/snapshot/").mock(
        return_value=httpx.Response(200, json={"schema_version": 1})
    )
    with LabClient.login(
        base_url="https://example.test", username="tester", password="test-only"
    ) as client:
        assert client.simulation is not None
        assert client.ml is not None
        client.live.snapshot(source="mofid")
    assert route.calls[0].request.headers["Authorization"] == "Token login-test-token"


@respx.mock
def test_ime_daily_adds_sorted_rows_without_changing_stats_contract():
    stats = {"count": 2, "stats": [{"trade_date": "2026-10-31"}, {"trade_date": "2026-10-30"}]}
    route = respx.get("https://example.test/api/v1/market/ime-cdc/GoldBar/stats/").mock(
        return_value=httpx.Response(200, json=stats)
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        rows = client.market.ime_daily("GoldBar", days=500)
        original = client.market.ime_cdc_stats("GoldBar")
        with pytest.raises(ValueError, match="code"):
            client.market.ime_daily("")
    assert [row["trade_date"] for row in rows] == ["2026-10-30", "2026-10-31"]
    assert original == stats
    assert route.calls[0].request.url.params["days"] == "180"


@respx.mock
def test_ml_experiments_use_authenticated_existing_transport():
    respx.get("https://example.test/api/v1/ml/experiments/").mock(
        return_value=httpx.Response(200, json={"results": [{"id": 7}], "next": None})
    )
    respx.get("https://example.test/api/v1/ml/experiments/7/").mock(
        return_value=httpx.Response(200, json={"id": 7})
    )
    train = respx.post("https://example.test/api/v1/ml/experiments/train/").mock(
        return_value=httpx.Response(202, json={"id": 8})
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        assert client.ml.list_experiments() == [{"id": 7}]
        assert client.ml.get_experiment(7) == {"id": 7}
        assert client.ml.train_probability_model(strategy_id="research", n_splits=3) == {"id": 8}
        with pytest.raises(ValueError, match="model_type"):
            client.ml.train_probability_model(model_type="unsupported")
    assert train.calls[0].request.headers["Authorization"] == "Token test-token"
    assert json.loads(train.calls[0].request.content) == {
        "label": "",
        "force": False,
        "strategy_id": "research",
        "n_splits": 3,
    }
