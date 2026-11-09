"""Mocked HTTP tests for FundAPI.candles (no live network)."""

from __future__ import annotations

import httpx
import pytest
import respx

from goldarb import LabClient


@respx.mock
def test_candles_1s_chunks_each_calendar_day():
    def _handler(request: httpx.Request) -> httpx.Response:
        day = request.url.params["date_from"]
        grain = request.url.params["grain"]
        assert grain == "1s"
        assert request.url.params["date_from"] == request.url.params["date_to"]
        return httpx.Response(
            200,
            json={
                "symbol": "طلا",
                "grain": "1s",
                "date_from": day,
                "date_to": day,
                "count": 1,
                "bars": [
                    {
                        "bar_at": f"{day}T10:00:01+00:00",
                        "open": 100000.0,
                        "high": 100100.0,
                        "low": 99900.0,
                        "close": 100050.0,
                        "volume": 10,
                        "nav_price": 99000.0,
                        "premium_discount_pct": 1.0606,
                    }
                ],
            },
        )

    route = respx.get("https://example.test/api/v1/funds/%D8%B7%D9%84%D8%A7/bars/").mock(
        side_effect=_handler
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        bars = client.fund.candles(
            "طلا",
            start="2026-07-01",
            end="2026-07-03",
            grain="1s",
        )
    assert route.call_count == 3
    assert len(bars) == 3
    assert [b["bar_at"][:10] for b in bars] == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
    ]


@respx.mock
def test_candles_rejects_unknown_grain():
    with LabClient(base_url="https://example.test", token="test-token") as client:
        with pytest.raises(ValueError, match="1s"):
            client.fund.candles("طلا", start="2026-07-01", end="2026-07-01", grain="5s")
