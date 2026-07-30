"""Small helpers shared by FundAPI / MarketAPI."""

from __future__ import annotations

from typing import Any


def rows_to_df(rows: list[dict[str, Any]], *, time_col: str | None = None) -> Any:
    """Convert row dicts to a pandas DataFrame (optional time index)."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError(
            "pandas is optional — pip install 'goldarb-lab[pandas]'"
        ) from exc
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if time_col and time_col in df.columns:
        df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
        df = df.set_index(time_col).sort_index()
    return df


def sort_by_key(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    rows.sort(key=lambda r: str(r.get(key) or ""))
    return rows


def alias_ohlc(row: dict[str, Any]) -> dict[str, Any]:
    """Copy ``*_price`` metal/USDT fields to short OHLCV names when missing."""
    out = dict(row)
    for src, dst in (
        ("open_price", "open"),
        ("high_price", "high"),
        ("low_price", "low"),
        ("close_price", "close"),
    ):
        if src in out and dst not in out:
            out[dst] = out[src]
    return out
