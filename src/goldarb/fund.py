"""Fund history helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, TYPE_CHECKING

from ._http import encode_symbol, iter_date_chunks

if TYPE_CHECKING:
    from ._http import LabHttp

# Must match backend funds.lab_bars.FUND_BARS_1M_MAX_DAYS / DAILY
_1M_MAX_SPAN = 7
_DAILY_MAX_SPAN = 366


class FundAPI:
    def __init__(self, http: LabHttp) -> None:
        self._http = http

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

    def candles_df(
        self,
        symbol: str,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1m",
    ) -> Any:
        """Same as ``candles`` but returns a pandas DataFrame (requires pandas)."""
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "pandas is optional — pip install 'goldarb-lab[pandas]'"
            ) from exc
        rows = self.candles(symbol, start=start, end=end, grain=grain)
        if not rows:
            return pd.DataFrame(
                columns=[
                    "bar_at",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "nav_price",
                    "premium_discount_pct",
                ]
            )
        df = pd.DataFrame(rows)
        if "bar_at" in df.columns:
            df["bar_at"] = pd.to_datetime(df["bar_at"], utc=True)
            df = df.set_index("bar_at").sort_index()
        return df

    def list_symbols(self) -> list[dict[str, Any]]:
        payload = self._http.get_json("/api/v1/funds/")
        return payload if isinstance(payload, list) else []
