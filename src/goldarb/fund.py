"""Fund history + live helpers for strategy notebooks."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Sequence

from ._http import encode_symbol, iter_date_chunks
from ._util import rows_to_df, sort_by_key

if TYPE_CHECKING:
    from ._http import LabHttp

# Must match backend funds.lab_bars.FUND_BARS_1M_MAX_DAYS / DAILY
_1M_MAX_SPAN = 7
_DAILY_MAX_SPAN = 366


class FundAPI:
    def __init__(self, http: LabHttp) -> None:
        self._http = http

    # --- historical bars -------------------------------------------------

    def candles(
        self,
        symbol: str,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1m",
    ) -> list[dict[str, Any]]:
        """
        Fetch fund bars. ``grain`` is ``1m`` or ``daily``.

        Long ranges are auto-chunked to respect platform limits.
        Includes ``close`` / ``premium_discount_pct`` / ``nav_price`` when present.
        """
        grain_key = grain.strip().lower()
        if grain_key not in {"1m", "daily"}:
            raise ValueError("grain must be '1m' or 'daily'")
        max_span = _1M_MAX_SPAN if grain_key == "1m" else _DAILY_MAX_SPAN
        path = f"/api/v1/funds/{encode_symbol(symbol)}/bars/"
        bars: list[dict[str, Any]] = []
        for a, b in iter_date_chunks(start, end, max_span_days=max_span):
            payload = self._http.get_json(
                path,
                {
                    "grain": grain_key,
                    "date_from": a.isoformat(),
                    "date_to": b.isoformat(),
                },
            )
            chunk = payload.get("bars") if isinstance(payload, dict) else None
            if isinstance(chunk, list):
                bars.extend(chunk)
        return bars

    def candles_many(
        self,
        symbols: Sequence[str],
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "daily",
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Fetch bars for many symbols (client-side loop — no bulk platform API yet).

        Useful for bubble-rank / basket strategies over the full gold-fund universe.
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for symbol in symbols:
            out[symbol] = self.candles(symbol, start=start, end=end, grain=grain)
        return out

    def candles_df(
        self,
        symbol: str,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1m",
    ) -> Any:
        """Same as ``candles`` but returns a pandas DataFrame (requires pandas)."""
        rows = self.candles(symbol, start=start, end=end, grain=grain)
        return rows_to_df(rows, time_col="bar_at")

    # --- universe / calibration ------------------------------------------

    def list_symbols(self) -> list[dict[str, Any]]:
        """Latest fund list (dashboard-oriented; prefer ``meta()`` for static ids)."""
        payload = self._http.get_json("/api/v1/funds/")
        return payload if isinstance(payload, list) else []

    def meta(self) -> list[dict[str, Any]]:
        """Static fund metadata: symbol, ins_code, name."""
        rows = self._http.get_paginated_results("/api/v1/funds/meta/")
        return sort_by_key(rows, "symbol")

    def comparison(self) -> list[dict[str, Any]]:
        """Dashboard comparison rows (price, premium, flow tip, liquidity)."""
        payload = self._http.get_json("/api/v1/funds/comparison/")
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            rows = payload.get("funds") or payload.get("results") or payload.get("rows")
            if isinstance(rows, list):
                return rows
        return []

    def spreads(self, *, window: int = 90) -> dict[str, Any]:
        """
        Pairwise premium-spread z-scores (F-6 / ``pair_zscore`` calibration).

        ``window`` must be ``30`` or ``90`` (platform constraint).
        """
        payload = self._http.get_json("/api/v1/funds/spreads/", {"window": int(window)})
        return payload if isinstance(payload, dict) else {"raw": payload}

    def premium_stats(
        self,
        symbol: str,
        *,
        window: int = 90,
        k: float = 2.0,
    ) -> dict[str, Any]:
        """Signed-premium percentile + mean±kσ bands (F-3)."""
        path = f"/api/v1/funds/{encode_symbol(symbol)}/premium-stats/"
        payload = self._http.get_json(path, {"window": int(window), "k": float(k)})
        return payload if isinstance(payload, dict) else {"raw": payload}

    # --- daily series used by Lab templates ------------------------------

    def flow(self, symbol: str, *, days: int = 365) -> list[dict[str, Any]]:
        """
        حقیقی/حقوقی flow history (``flow_divergence`` needs buy/sell vol_n).

        Newest-first from API; returned ascending by ``date``.
        """
        path = f"/api/v1/funds/{encode_symbol(symbol)}/flow/"
        rows = self._http.get_paginated_results(path, {"days": int(days)})
        return sort_by_key(rows, "date")

    def flow_df(self, symbol: str, *, days: int = 365) -> Any:
        return rows_to_df(self.flow(symbol, days=days), time_col="date")

    def bubbles(self, symbol: str, *, days: int = 365) -> list[dict[str, Any]]:
        """Historical bubble metrics (nominal / real / intrinsic %)."""
        path = f"/api/v1/funds/{encode_symbol(symbol)}/bubbles/"
        rows = self._http.get_paginated_results(path, {"days": int(days)})
        return sort_by_key(rows, "date")

    def bubbles_df(self, symbol: str, *, days: int = 365) -> Any:
        return rows_to_df(self.bubbles(symbol, days=days), time_col="date")

    # --- composition / fair NAV (latest snapshot) ------------------------

    def holdings(self, symbol: str) -> dict[str, Any]:
        """Latest Codal/manual holdings mix for one fund."""
        path = f"/api/v1/funds/{encode_symbol(symbol)}/holdings/"
        payload = self._http.get_json(path)
        return payload if isinstance(payload, dict) else {"raw": payload}

    def holdings_all(self) -> Any:
        """Latest holdings for all gold funds."""
        return self._http.get_json("/api/v1/funds/holdings/")

    def fair_nav(self, symbol: str) -> dict[str, Any]:
        """Composition / lag-1 grams fair NAV estimate (labeled تخمینی)."""
        path = f"/api/v1/funds/{encode_symbol(symbol)}/fair-nav/"
        payload = self._http.get_json(path)
        return payload if isinstance(payload, dict) else {"raw": payload}

    # --- live tips (paper-live / signal gates) ---------------------------

    def orderbook(self, symbol: str) -> dict[str, Any]:
        """Latest BestLimits for one fund (live only — no history API)."""
        path = f"/api/v1/funds/{encode_symbol(symbol)}/orderbook/"
        payload = self._http.get_json(path)
        return payload if isinstance(payload, dict) else {"raw": payload}

    def orderbooks(self) -> Any:
        """Latest BestLimits for all gold funds."""
        return self._http.get_json("/api/v1/funds/orderbook/")

    def last_price(self, symbol: str) -> dict[str, Any]:
        path = f"/api/v1/funds/{encode_symbol(symbol)}/last-price/"
        payload = self._http.get_json(path)
        return payload if isinstance(payload, dict) else {"raw": payload}

    def last_prices(self) -> Any:
        return self._http.get_json("/api/v1/funds/last-price/")

    def nav_live(self, symbol: str) -> dict[str, Any]:
        path = f"/api/v1/funds/{encode_symbol(symbol)}/nav/live/"
        payload = self._http.get_json(path)
        return payload if isinstance(payload, dict) else {"raw": payload}

    def navs_live(self) -> Any:
        return self._http.get_json("/api/v1/funds/nav/live/")

    def symbols(self) -> list[str]:
        """Convenience: sorted symbol strings from ``meta()``."""
        return [str(r["symbol"]) for r in self.meta() if r.get("symbol")]
