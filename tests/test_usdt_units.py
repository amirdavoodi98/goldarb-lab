"""Mocked HTTP tests for USDT + issued-units helpers (no live network)."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import httpx
import respx

from goldarb import LabClient


@respx.mock
def test_usdt_lookback_sorted_ascending():
    respx.get("https://example.test/api/v1/market/usdt/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "results": [
                    {
                        "bar_at": "2026-07-02T01:00:00Z",
                        "close_price": "920000",
                        "source": "nobitex",
                    },
                    {
                        "bar_at": "2026-07-02T00:00:00Z",
                        "close_price": "910000",
                        "source": "import",
                    },
                ],
            },
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        bars = client.market.usdt(days=2)
    assert [b["bar_at"] for b in bars] == [
        "2026-07-02T00:00:00Z",
        "2026-07-02T01:00:00Z",
    ]
    assert bars[0]["close"] == "910000"


@respx.mock
def test_usdt_start_end_chunks_and_filters():
    """Span > 31d triggers multiple lookbacks; results filtered + ascending."""
    today = date(2026, 8, 10)

    def _handler(request: httpx.Request) -> httpx.Response:
        days = int(request.url.params.get("days", "7"))
        rows = []
        for i in range(days):
            d = today - timedelta(days=i)
            rows.append(
                {
                    "bar_at": f"{d.isoformat()}T12:00:00Z",
                    "close_price": str(900000 + i),
                    "source": "nobitex",
                }
            )
        return httpx.Response(
            200, json={"count": len(rows), "next": None, "results": rows}
        )

    route = respx.get("https://example.test/api/v1/market/usdt/").mock(
        side_effect=_handler
    )

    with (
        patch("goldarb.market._calendar_today", return_value=today),
        LabClient(base_url="https://example.test", token="test-token") as client,
    ):
        bars = client.market.usdt(start="2026-07-01", end="2026-08-10")

    assert route.call_count >= 2
    assert bars
    assert bars == sorted(bars, key=lambda r: r["bar_at"])
    days = {date.fromisoformat(str(b["bar_at"])[:10]) for b in bars}
    assert min(days) >= date(2026, 7, 1)
    assert max(days) <= date(2026, 8, 10)


@respx.mock
def test_usdt_live_dict():
    respx.get("https://example.test/api/v1/market/usdt/live/").mock(
        return_value=httpx.Response(
            200,
            json={
                "last_irr": 91000.0,
                "best_bid_irr": 90950.0,
                "best_ask_irr": 91050.0,
                "status": "ok",
                "age_seconds": 12.0,
                "source": "nobitex",
                "grain": "live",
                "unit": "toman",
            },
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        tip = client.market.usdt_live()
    assert tip["unit"] == "toman"
    assert tip["last_irr"] == 91000.0
    assert tip["status"] == "ok"


@respx.mock
def test_issued_units_from_nav_live():
    respx.get("https://example.test/api/v1/funds/%D8%B7%D9%84%D8%A7/nav/live/").mock(
        return_value=httpx.Response(
            200,
            json={
                "symbol": "طلا",
                "nav_red": 1_200_000.0,
                "units": 50_000_000,
                "units_deven": "20260730",
                "as_of": "2026-07-30T12:00:00+00:00",
                "status": "ok",
                "source": "tsetmc",
                "age_seconds": 30.0,
            },
        )
    )
    with LabClient(base_url="https://example.test", token="test-token") as client:
        full = client.fund.nav_live("طلا")
        thin = client.fund.issued_units("طلا")
    assert full["units"] == 50_000_000
    assert thin["units"] == 50_000_000
    assert thin["units_deven"] == "20260730"
    assert thin["grain"] == "near_daily"
