"""Mocked HTTP tests for IME CDC helpers."""

from __future__ import annotations

import httpx
import respx

from goldarb import LabClient


@respx.mock
def test_ime_cdc_live_board():
    respx.get("https://example.test/api/v1/market/ime-cdc/").mock(
        return_value=httpx.Response(
            200,
            json={"contracts": [{"contract_code": "SilverBar", "last_traded_price": 1.0}]},
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        payload = client.market.ime_cdc_live()
    assert payload["contracts"][0]["contract_code"] == "SilverBar"


@respx.mock
def test_ime_cdc_live_detail():
    respx.get("https://example.test/api/v1/market/ime-cdc/GoldBar/").mock(
        return_value=httpx.Response(
            200,
            json={"contract_code": "GoldBar", "last_traded_price": 2.5},
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        payload = client.market.ime_cdc_live("GoldBar")
    assert payload["contract_code"] == "GoldBar"


@respx.mock
def test_ime_cdc_stats_silver():
    respx.get("https://example.test/api/v1/market/ime-cdc/SilverBar/stats/").mock(
        return_value=httpx.Response(
            200,
            json={
                "contract_code": "SilverBar",
                "count": 1,
                "days": 30,
                "stats": [{"trade_date": "2026-07-13", "last_price": 105.0}],
            },
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        payload = client.market.ime_cdc_stats("SilverBar", days=30)
    assert payload["contract_code"] == "SilverBar"
    assert payload["stats"][0]["trade_date"] == "2026-07-13"


@respx.mock
def test_ime_cdc_arbitrage():
    respx.get("https://example.test/api/v1/market/ime-cdc/arbitrage/").mock(
        return_value=httpx.Response(
            200,
            json={"benchmark": "GoldBar", "rows": []},
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        payload = client.market.ime_cdc_arbitrage(benchmark="GoldBar")
    assert payload["benchmark"] == "GoldBar"
