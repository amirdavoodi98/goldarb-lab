"""Mocked HTTP tests (no live network)."""

from __future__ import annotations

import httpx
import respx

from goldarb import LabClient


@respx.mock
def test_fund_candles_chunks_http():
    route = respx.get("https://example.test/api/v1/funds/%D8%B7%D9%84%D8%A7/bars/").mock(
        return_value=httpx.Response(
            200,
            json={
                "bars": [
                    {
                        "bar_at": "2026-07-01T00:00:00Z",
                        "open": 1,
                        "high": 2,
                        "low": 1,
                        "close": 2,
                        "volume": 10,
                    }
                ]
            },
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        bars = client.fund.candles(
            "طلا",
            start="2026-07-01",
            end="2026-07-10",
            grain="1m",
        )
    assert len(bars) == 2  # two 7-day chunks, one bar each
    assert route.call_count == 2


@respx.mock
def test_xau_metal_bars_paginated():
    respx.get("https://example.test/api/v1/market/metals/bars/").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "count": 2,
                    "next": "https://example.test/api/v1/market/metals/bars/?page=2",
                    "results": [{"bar_at": "2026-07-02T00:00:00Z", "close": 2400}],
                },
            ),
            httpx.Response(
                200,
                json={
                    "count": 2,
                    "next": None,
                    "results": [{"bar_at": "2026-07-01T00:00:00Z", "close": 2390}],
                },
            ),
        ]
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        bars = client.market.xau(start="2026-07-01", end="2026-07-02", grain="1m")
    assert [b["close"] for b in bars] == [2390, 2400]
