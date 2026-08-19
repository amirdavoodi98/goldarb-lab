"""Mocked HTTP tests for strategy data wrappers (no live network)."""

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
    assert len(bars) == 2
    assert route.call_count == 2


@respx.mock
def test_fund_candles_1s_chunks_one_day_each():
    route = respx.get("https://example.test/api/v1/funds/%D8%B7%D9%84%D8%A7/bars/").mock(
        return_value=httpx.Response(
            200,
            json={
                "bars": [
                    {
                        "bar_at": "2026-08-16T10:00:01",
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
            start="2026-08-16",
            end="2026-08-19",
            grain="1s",
        )
    assert len(bars) == 4
    assert route.call_count == 4
    params = [tuple(sorted(c.request.url.params.multi_items())) for c in route.calls]
    assert ("grain", "1s") in params[0]
    assert ("date_from", "2026-08-16") in params[0]
    assert ("date_to", "2026-08-16") in params[0]
    assert ("date_from", "2026-08-19") in params[-1]
    assert ("date_to", "2026-08-19") in params[-1]


@respx.mock
def test_xau_metal_bars_paginated_aliases_ohlc():
    respx.get("https://example.test/api/v1/market/metals/bars/").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "count": 2,
                    "next": "https://example.test/api/v1/market/metals/bars/?page=2",
                    "results": [
                        {
                            "bar_at": "2026-07-02T00:00:00Z",
                            "close_price": "2400",
                            "open_price": "2395",
                        }
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "count": 2,
                    "next": None,
                    "results": [
                        {
                            "bar_at": "2026-07-01T00:00:00Z",
                            "close_price": "2390",
                            "open_price": "2388",
                        }
                    ],
                },
            ),
        ]
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        bars = client.market.xau(start="2026-07-01", end="2026-07-02", grain="1m")
    assert [b["close"] for b in bars] == ["2390", "2400"]
    assert bars[0]["close_price"] == "2390"


@respx.mock
def test_flow_and_usdt_sorted_ascending():
    respx.get("https://example.test/api/v1/funds/%D8%B7%D9%84%D8%A7/flow/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"date": "2026-07-02", "buy_vol_n": 10, "sell_vol_n": 3},
                {"date": "2026-07-01", "buy_vol_n": 5, "sell_vol_n": 8},
            ],
        )
    )
    respx.get("https://example.test/api/v1/market/usdt/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "results": [
                    {"bar_at": "2026-07-02T01:00:00Z", "close_price": "920000"},
                    {"bar_at": "2026-07-02T00:00:00Z", "close_price": "910000"},
                ],
            },
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        flow = client.fund.flow("طلا", days=30)
        usdt = client.market.usdt(days=2)
    assert [r["date"] for r in flow] == ["2026-07-01", "2026-07-02"]
    assert [r["close"] for r in usdt] == ["910000", "920000"]


@respx.mock
def test_spreads_premium_stats_snapshot():
    respx.get("https://example.test/api/v1/funds/spreads/").mock(
        return_value=httpx.Response(200, json={"window": 90, "pairs": []})
    )
    respx.get(
        "https://example.test/api/v1/funds/%D8%B7%D9%84%D8%A7/premium-stats/"
    ).mock(return_value=httpx.Response(200, json={"window": 90, "n": 80}))
    respx.get("https://example.test/api/v1/market/live-snapshot/").mock(
        return_value=httpx.Response(
            200, json={"usable_for_signals": True, "refs": {}, "funds": []}
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        spreads = client.fund.spreads(window=90)
        stats = client.fund.premium_stats("طلا", window=90, k=2)
        snap = client.market.live_snapshot(include=("refs", "funds"))
    assert spreads["window"] == 90
    assert stats["n"] == 80
    assert snap["usable_for_signals"] is True


@respx.mock
def test_candles_many_loops_symbols():
    respx.get("https://example.test/api/v1/funds/%D8%B7%D9%84%D8%A7/bars/").mock(
        return_value=httpx.Response(200, json={"bars": [{"bar_at": "a", "close": 1}]})
    )
    respx.get("https://example.test/api/v1/funds/%D8%B2%D8%B1/bars/").mock(
        return_value=httpx.Response(200, json={"bars": [{"bar_at": "b", "close": 2}]})
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        out = client.fund.candles_many(
            ["طلا", "زر"],
            start="2026-07-01",
            end="2026-07-02",
            grain="daily",
        )
    assert set(out) == {"طلا", "زر"}
    assert out["زر"][0]["close"] == 2
