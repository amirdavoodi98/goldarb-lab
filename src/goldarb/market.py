"""Market / spot history helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, TYPE_CHECKING

from ._http import iter_date_chunks

if TYPE_CHECKING:
    from ._http import LabHttp

_METAL_1M_MAX_SPAN = 31


class MarketAPI:
    def __init__(self, http: LabHttp) -> None:
        self._http = http

    def xau(
        self,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1m",
    ) -> list[dict[str, Any]]:
        """XAUUSD bars. ``grain=1m`` uses metal bars API; ``daily`` uses gold history."""
        grain_key = grain.strip().lower()
        if grain_key == "1m":
            return self._metal_bars("XAUUSD", start=start, end=end)
        if grain_key == "daily":
            return self.gold_daily(date_from=start, date_to=end)
        raise ValueError("grain must be '1m' or 'daily'")

    def xag(
        self,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1m",
    ) -> list[dict[str, Any]]:
        grain_key = grain.strip().lower()
        if grain_key != "1m":
            raise ValueError("xag currently supports grain='1m' only")
        return self._metal_bars("XAGUSD", start=start, end=end)

    def _metal_bars(
        self,
        symbol: str,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
    ) -> list[dict[str, Any]]:
        bars: list[dict[str, Any]] = []
        for a, b in iter_date_chunks(start, end, max_span_days=_METAL_1M_MAX_SPAN):
            chunk = self._http.get_paginated_results(
                "/api/v1/market/metals/bars/",
                {
                    "symbol": symbol,
                    "date_from": a.isoformat(),
                    "date_to": b.isoformat(),
                    "page_size": 500,
                },
            )
            bars.extend(chunk)
        # API returns newest-first; normalize ascending for strategy work
        bars.sort(key=lambda r: str(r.get("bar_at") or ""))
        return bars

    def gold_daily(
        self,
        *,
        days: int | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Daily ``GoldPrice`` rows (xau_usd, gold_18k_irr, …).

        Prefer ``days=`` for a simple lookback, or pass ``date_from``/``date_to``
        and filter client-side (platform endpoint is primarily ``days``-based).
        """
        params: dict[str, Any] = {}
        if days is not None:
            params["days"] = int(days)
        elif date_from is not None and date_to is not None:
            # Pull a wide window then filter — gold endpoint uses days= lookback.
            from datetime import date as date_cls

            from ._http import _parse_day

            a = _parse_day(date_from)
            b = _parse_day(date_to)
            params["days"] = max(1, (date_cls.today() - a).days + 5)
        else:
            params["days"] = 90
        rows = self._http.get_paginated_results("/api/v1/market/gold/", params)
        if date_from is not None and date_to is not None:
            from ._http import _parse_day

            a = _parse_day(date_from)
            b = _parse_day(date_to)
            filtered: list[dict[str, Any]] = []
            for row in rows:
                raw = row.get("date")
                if raw is None:
                    continue
                d = _parse_day(str(raw))
                if a <= d <= b:
                    filtered.append(row)
            filtered.sort(key=lambda r: str(r.get("date") or ""))
            return filtered
        rows.sort(key=lambda r: str(r.get("date") or ""))
        return rows
