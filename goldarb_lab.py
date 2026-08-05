"""
market_data.py — main-project wrappers around the goldarb-lab SDK.

Each function maps to one required data feed for the gold-fund arbitrage
system. Every call here is verified against the real SDK source
(fund.py / market.py) and its respx-mocked test suite — nothing guessed.

Confirmed NOT available anywhere in the SDK or the platform's urls.py:
  - Gold options symbols (اختیار معامله) — no route exists on the backend.

Confirmed available but scoped differently than "per-investor units":
  - fund.issued_units() / fund.nav_live() return the FUND'S TOTAL
    outstanding units, near-daily as-of (TSETMC `units_deven`), not a
    specific investor's position and not intraday.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from goldarb import LabClient

DEFAULT_METAL_LOOKBACK_DAYS = 7   # xau/xag 1m — SDK auto-chunks past 31d anyway
DEFAULT_IME_STATS_DAYS = 90       # ime_cdc_stats clamps to 1..180 internally
DEFAULT_USDT_LOOKBACK_DAYS = 2    # usdt(days=) clamps to 1..31 internally


# ---------------------------------------------------------------------
# 1. قیمت انس جهانی طلا و نقره  (global XAU / XAG spot)
# ---------------------------------------------------------------------

def get_xau_xag_live(client: LabClient) -> dict[str, Any]:
    """Near-live XAU/XAG tip with freshness info (spot_live -> market/spot/live/)."""
    return client.market.spot_live()


def get_xau_bars(client: LabClient, *, days: int = DEFAULT_METAL_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Recent XAUUSD 1m bars."""
    end = date.today()
    start = end - timedelta(days=days)
    return client.market.xau(start=start.isoformat(), end=end.isoformat(), grain="1m")


def get_xag_bars(client: LabClient, *, days: int = DEFAULT_METAL_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Recent XAGUSD 1m bars."""
    end = date.today()
    start = end - timedelta(days=days)
    return client.market.xag(start=start.isoformat(), end=end.isoformat(), grain="1m")


# ---------------------------------------------------------------------
# 2. قیمت تتر نوبیتکس (USDT/IRT — unit is TOMAN, source may be import|nobitex)
# ---------------------------------------------------------------------

def get_usdt_live(client: LabClient) -> dict[str, Any]:
    """Near-live USDT/IRT tip (Nobitex-fed; SDK never scrapes Nobitex directly)."""
    return client.market.usdt_live()


def get_usdt_bars(client: LabClient, *, days: int = DEFAULT_USDT_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Recent USDT/IRT 1m bars."""
    return client.market.usdt(days=days)


# ---------------------------------------------------------------------
# 3 & 4. قیمت سکه طلا / شمش طلا  (IME CDC contracts — catalogue codes only)
# ---------------------------------------------------------------------

def get_gold_coin_live(client: LabClient) -> dict[str, Any]:
    return client.market.ime_cdc_live("GoldCoin")


def get_gold_bar_live(client: LabClient) -> dict[str, Any]:
    return client.market.ime_cdc_live("GoldBar")


def get_gold_coin_history(client: LabClient, *, days: int = DEFAULT_IME_STATS_DAYS) -> dict[str, Any]:
    return client.market.ime_cdc_stats("GoldCoin", days=days)


def get_gold_bar_history(client: LabClient, *, days: int = DEFAULT_IME_STATS_DAYS) -> dict[str, Any]:
    return client.market.ime_cdc_stats("GoldBar", days=days)


# ---------------------------------------------------------------------
# 5. نمادهای اختیار معامله طلا (gold options symbols)
# ---------------------------------------------------------------------
# NOT AVAILABLE. Confirmed absent from:
#   - goldarb/fund.py, goldarb/market.py (no method references "option")
#   - the platform's full urls.py (no market/options/ or similar route)
# Left as an explicit stub so callers fail loudly instead of silently
# getting None back from a made-up endpoint.

def get_gold_options() -> None:
    raise NotImplementedError(
        "No options/اختیار معامله endpoint exists on this platform "
        "(confirmed against urls.py) — not available via goldarb-lab."
    )


# ---------------------------------------------------------------------
# 6. پورتفولیوی صندوق‌ها: ترکیب دارایی + تعداد واحدها (fund-wide, not per-investor)
# ---------------------------------------------------------------------

def get_fund_holdings(client: LabClient, symbol: str) -> dict[str, Any]:
    """Latest asset-composition mix (%) for one fund."""
    return client.fund.holdings(symbol)


def get_all_funds_holdings(client: LabClient) -> Any:
    """Latest asset-composition mix for all gold funds."""
    return client.fund.holdings_all()


def get_fund_issued_units(client: LabClient, symbol: str) -> dict[str, Any]:
    """
    Total outstanding ETF units for the fund.
    Near-daily as-of (units_deven, TSETMC) — NOT a specific investor's
    position, NOT intraday. If you need a per-investor unit count, this
    SDK does not expose it.
    """
    return client.fund.issued_units(symbol)


def get_all_funds_nav_live(client: LabClient) -> Any:
    """Near-live NAV tips for all gold funds (includes units where present)."""
    return client.fund.navs_live()


# ---------------------------------------------------------------------
# Orchestrator — one call per arbitrage-loop tick
# ---------------------------------------------------------------------

def fetch_arbitrage_snapshot(client: LabClient, fund_symbols: tuple[str, ...] = ("طلا",)) -> dict[str, Any]:
    """
    Pull everything the arbitrage system needs in one call, using an
    already-open LabClient (see goldarb_client.get_client()) so the
    connection pool is reused across ticks instead of reconnecting each time.
    """
    return {
        "xau_xag_live": get_xau_xag_live(client),
        "usdt_live": get_usdt_live(client),
        "gold_coin_live": get_gold_coin_live(client),
        "gold_bar_live": get_gold_bar_live(client),
        "options": None,  # unavailable — see get_gold_options()
        "funds_holdings": {sym: get_fund_holdings(client, sym) for sym in fund_symbols},
        "funds_issued_units": {sym: get_fund_issued_units(client, sym) for sym in fund_symbols},
    }


if __name__ == "__main__":
    from goldarb import LabClient

    client = LabClient.login(
        base_url="https://goldarb.ir",
        username="shahrzad",
        password="3p41IKv3KwJi",
    )

    try:
        data = fetch_arbitrage_snapshot(client)

        for key, value in data.items():
            print(f"{key}:")
            print(value)
            print("-" * 50)

    finally:
        client.close()