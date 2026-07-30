"""Market / spot history + live snapshot helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Sequence

from ._http import _parse_day, iter_date_chunks
from ._util import alias_ohlc, rows_to_df, sort_by_key

if TYPE_CHECKING:
    from ._http import LabHttp

_METAL_1M_MAX_SPAN = 31
_USDT_MAX_DAYS = 31
_LIVE_SNAPSHOT_INCLUDES = frozenset({"refs", "funds", "orderbook", "ime", "fair_nav"})


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

    def xau_df(
        self,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1m",
    ) -> Any:
        return rows_to_df(
            self.xau(start=start, end=end, grain=grain),
            time_col="bar_at" if grain.strip().lower() == "1m" else "date",
        )

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
            bars.extend(alias_ohlc(r) if isinstance(r, dict) else r for r in chunk)
        return sort_by_key(bars, "bar_at")

    def gold_daily(
        self,
        *,
        days: int | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Daily ``GoldPrice`` rows (xau_usd, gold_18k_irr, usd_irr, xag_usd).

        Prefer ``days=`` for a simple lookback, or pass ``date_from``/``date_to``
        and filter client-side (platform endpoint is primarily ``days``-based).
        """
        params: dict[str, Any] = {}
        if days is not None:
            params["days"] = int(days)
        elif date_from is not None and date_to is not None:
            from datetime import date as date_cls

            a = _parse_day(date_from)
            params["days"] = max(1, (date_cls.today() - a).days + 5)
        else:
            params["days"] = 90
        rows = self._http.get_paginated_results("/api/v1/market/gold/", params)
        if date_from is not None and date_to is not None:
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
            return sort_by_key(filtered, "date")
        return sort_by_key(rows, "date")

    def gold_daily_df(
        self,
        *,
        days: int | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
    ) -> Any:
        return rows_to_df(
            self.gold_daily(days=days, date_from=date_from, date_to=date_to),
            time_col="date",
        )

    def usdt(self, *, days: int = 7) -> list[dict[str, Any]]:
        """
        USDT/IRR 1-minute bars (platform clamp ≤ 31 days).

        Returned ascending by ``bar_at`` with short OHLC aliases.
        """
        days_clamped = max(1, min(int(days), _USDT_MAX_DAYS))
        rows = self._http.get_paginated_results(
            "/api/v1/market/usdt/",
            {"days": days_clamped, "page_size": 500},
        )
        aliased = [alias_ohlc(r) if isinstance(r, dict) else r for r in rows]
        return sort_by_key(aliased, "bar_at")

    def usdt_df(self, *, days: int = 7) -> Any:
        return rows_to_df(self.usdt(days=days), time_col="bar_at")

    # --- live (paper-live / signal trust gate) ---------------------------

    def live_snapshot(
        self,
        *,
        include: Sequence[str] | str = ("refs", "funds"),
    ) -> dict[str, Any]:
        """
        F-19 unified live snapshot.

        ``include`` values: ``refs``, ``funds``, ``orderbook``, ``ime``, ``fair_nav``.
        """
        if isinstance(include, str):
            parts = [p.strip() for p in include.split(",") if p.strip()]
        else:
            parts = [str(p).strip() for p in include if str(p).strip()]
        unknown = set(parts) - _LIVE_SNAPSHOT_INCLUDES
        if unknown:
            raise ValueError(
                f"unknown include={sorted(unknown)}; "
                f"allowed={sorted(_LIVE_SNAPSHOT_INCLUDES)}"
            )
        payload = self._http.get_json(
            "/api/v1/market/live-snapshot/",
            {"include": ",".join(parts)},
        )
        return payload if isinstance(payload, dict) else {"raw": payload}

    def refs_live(self) -> dict[str, Any]:
        """Near-live domestic refs (gold18 / USD / coin)."""
        payload = self._http.get_json("/api/v1/market/refs/live/")
        return payload if isinstance(payload, dict) else {"raw": payload}

    def spot_live(self) -> dict[str, Any]:
        """Near-live XAU/XAG tip with freshness."""
        payload = self._http.get_json("/api/v1/market/spot/live/")
        return payload if isinstance(payload, dict) else {"raw": payload}
