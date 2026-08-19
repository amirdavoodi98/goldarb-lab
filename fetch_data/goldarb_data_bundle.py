"""
goldarb_data_bundle.py — shared fetch helpers for the fetch_data scripts.

CANONICAL LOCATION: fetch_data/goldarb_data_bundle.py (this file must
live inside the fetch_data/ package — most scripts import it with a
relative import: `from .goldarb_data_bundle import ...`).

Every function here accepts an already-authenticated LabClient.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from goldarb import LabClient

DEFAULT_METAL_LOOKBACK_DAYS = 7
DEFAULT_IME_STATS_DAYS = 90
DEFAULT_USDT_LOOKBACK_DAYS = 2


# ---------------------------------------------------------------------
# Global XAU/XAG spot
# ---------------------------------------------------------------------

def get_xau_xag_live(client: LabClient) -> dict[str, Any]:
    return client.market.spot_live()


def get_xau_bars(client: LabClient, *, days: int = DEFAULT_METAL_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=days)
    return client.market.xau(start=start.isoformat(), end=end.isoformat(), grain="1m")


def get_xag_bars(client: LabClient, *, days: int = DEFAULT_METAL_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=days)
    return client.market.xag(start=start.isoformat(), end=end.isoformat(), grain="1m")


# ---------------------------------------------------------------------
# Nobitex USDT/IRT
# ---------------------------------------------------------------------

def get_usdt_live(client: LabClient) -> dict[str, Any]:
    return client.market.usdt_live()


def get_usdt_bars(client: LabClient, *, days: int = DEFAULT_USDT_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    return client.market.usdt(days=days)


# ---------------------------------------------------------------------
# IME CDC — GoldCoin / GoldBar
# ---------------------------------------------------------------------

def get_gold_coin_live(client: LabClient) -> dict[str, Any]:
    return client.market.ime_cdc_live("GoldCoin")


def get_gold_bar_live(client: LabClient) -> dict[str, Any]:
    return client.market.ime_cdc_live("GoldBar")


def get_gold_coin_history(client: LabClient, *, days: int = DEFAULT_IME_STATS_DAYS) -> dict[str, Any]:
    return client.market.ime_cdc_stats("GoldCoin", days=days)


def get_gold_bar_history(client: LabClient, *, days: int = DEFAULT_IME_STATS_DAYS) -> dict[str, Any]:
    return client.market.ime_cdc_stats("GoldBar", days=days)


def get_silver_bar_live(client: LabClient) -> dict[str, Any]:
    return client.market.ime_cdc_live("SilverBar")


def get_silver_bar_history(client: LabClient, *, days: int = DEFAULT_IME_STATS_DAYS) -> dict[str, Any]:
    return client.market.ime_cdc_stats("SilverBar", days=days)


# ---------------------------------------------------------------------
# Gold options — confirmed NOT available (no route in SDK or urls.py)
# ---------------------------------------------------------------------

def get_gold_options() -> None:
    raise NotImplementedError(
        "No options/اختیار معامله endpoint exists on this platform "
        "(confirmed against urls.py) — not available via goldarb-lab."
    )


# ---------------------------------------------------------------------
# Fund holdings / issued units (fund-wide, single current snapshot)
# ---------------------------------------------------------------------

def get_fund_holdings(client: LabClient, symbol: str) -> dict[str, Any]:
    return client.fund.holdings(symbol)


def get_all_funds_holdings(client: LabClient) -> Any:
    return client.fund.holdings_all()


def get_fund_issued_units(client: LabClient, symbol: str) -> dict[str, Any]:
    return client.fund.issued_units(symbol)


def get_all_funds_nav_live(client: LabClient) -> Any:
    return client.fund.navs_live()


# ---------------------------------------------------------------------
# Fund minute bars
# ---------------------------------------------------------------------

def get_fund_candles_1m(
    client: LabClient, symbol: str, *, start: str, end: str
) -> list[dict[str, Any]]:
    """
    Fund 1-minute bars. SDK auto-chunks requests >7 days into multiple
    calls internally (fund.py: _1M_MAX_SPAN=7) — a wider start/end is
    handled for you, no manual chunking needed.
    """
    return client.fund.candles(symbol, start=start, end=end, grain="1m")


# ---------------------------------------------------------------------
# Combined snapshot
# ---------------------------------------------------------------------

def fetch_arbitrage_snapshot(client: LabClient, fund_symbols: tuple[str, ...] = ("طلا",)) -> dict[str, Any]:
    return {
        "xau_xag_live": get_xau_xag_live(client),
        "usdt_live": get_usdt_live(client),
        "gold_coin_live": get_gold_coin_live(client),
        "gold_bar_live": get_gold_bar_live(client),
        "options": None,
        "funds_holdings": {sym: get_fund_holdings(client, sym) for sym in fund_symbols},
        "funds_issued_units": {sym: get_fund_issued_units(client, sym) for sym in fund_symbols},
    }