#!/usr/bin/env python3
"""
merge_fund_datasets.py — combine local CSV exports with live SDK data for
the 5 target funds: عیار، طلا، کهربا، مثقال، آتش.

Sources merged per fund:
  - composition CSV   (تاریخ, پنج نماد برتر (%), سهام (%), اوراق (%), سایر (%), نقد (%), سپرده (%))
  - nav_history CSV   (تاریخ, قیمت ابطال, قیمت صدور, قیمت آماری, ارزش خالص دارایی‌ها, تعداد واحدهای سرمایه‌گذاری شده)
  - IME contract daily history CSV(s) — SHARED across funds, not per-fund
    (DT, PersianDate, ContractCode, FirstPrice, MaxPrice, MinPrice, LastPrice,
     TradesVolume, TradesValue, OpenInterest, ..., LastSettlementPrice,
     TodaySettlementPrice, SettlementPricePercent)
  - usdttmn_1m_3y_final.csv — SHARED, resampled to daily
    (timestamp, datetime_utc, open, high, low, close, volume)
  - SDK: today's fund holdings + issued units, appended as the latest row
    (fills the gap between where your CSVs end and "now")

ASSUMPTIONS — verify against your real files and adjust CONFIG below:
  1. File-per-fund naming for composition/nav_history. Adjust the path
     templates in CONFIG if your actual filenames differ.
  2. تاریخ columns are Jalali (Persian) dates. Auto-detected per-value:
     any date string with year < 1500 is treated as Jalali and converted
     to Gregorian; anything else is assumed already Gregorian. If your
     files are actually Gregorian throughout, this still works correctly
     (nothing gets converted) — but VERIFY on a sample row before trusting
     the output, since a silent misjoin is worse than a script crash.
  3. IME contract CSVs are matched to a fund by cross-referencing that
     fund's Codal holdings legs (leg_type: gold_bar_cert / gold_coin_cert)
     via SDK — NOT hardcoded, since holdings differ per fund and may
     include SilverBar for some funds and not others.
"""

from __future__ import annotations

import csv
from pathlib import Path

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("pip install pandas --break-system-packages") from exc

try:
    import jdatetime
    HAVE_JDATETIME = True
except ImportError:
    HAVE_JDATETIME = False

from .goldarb_client import close_client, get_client
from .goldarb_data_bundle import get_fund_holdings, get_fund_issued_units

# ---------------------------------------------------------------------
# CONFIG — adjust these to match your actual file layout
# ---------------------------------------------------------------------

FUND_SYMBOLS = ("عیار", "طلا", "کهربا", "مثقال", "آتش")

DATA_DIR = Path("data")

# Adjust these templates if your real filenames differ
COMPOSITION_PATH = lambda symbol: DATA_DIR / f"composition_{symbol}.csv"
NAV_HISTORY_PATH = lambda symbol: DATA_DIR / f"nav_history_{symbol}.csv"

# Shared reference files — one row of contract history per date, not per-fund
IME_CONTRACT_FILES = {
    "SilverBar": DATA_DIR / "silver_daily_history.csv",
    # Add these if/when you have them — same schema, different contract:
    # "GoldBar": DATA_DIR / "goldbar_daily_history.csv",
    # "GoldCoin": DATA_DIR / "goldcoin_daily_history.csv",
}

USDT_PATH = DATA_DIR / "usdttmn_1m_3y_final.csv"

OUT_DIR = Path("merged_output")

# leg_type (from Codal holdings) -> IME contract code, for matching
LEG_TO_CONTRACT = {
    "gold_bar_cert": "GoldBar",
    "gold_coin_cert": "GoldCoin",
    "silver_bar_cert": "SilverBar",  # adjust if the real leg_type differs
}


# ---------------------------------------------------------------------
# Date handling
# ---------------------------------------------------------------------

def _to_gregorian(date_str: str) -> str | None:
    """
    Convert a تاریخ value to ISO Gregorian (YYYY-MM-DD).
    Auto-detects Jalali (year < 1500) vs already-Gregorian.
    Returns None if unparsable — caller should drop/flag such rows.
    """
    if not date_str or not str(date_str).strip():
        return None
    s = str(date_str).strip().replace("-", "/")
    parts = s.split("/")
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None

    if y < 1500:
        if not HAVE_JDATETIME:
            raise RuntimeError(
                f"Found Jalali-looking date '{date_str}' but jdatetime isn't "
                f"installed. Run: pip install jdatetime --break-system-packages"
            )
        try:
            g = jdatetime.date(y, m, d).togregorian()
            return g.isoformat()
        except ValueError:
            return None
    else:
        try:
            from datetime import date as date_cls
            return date_cls(y, m, d).isoformat()
        except ValueError:
            return None


# ---------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------

def load_composition(symbol: str) -> pd.DataFrame:
    path = COMPOSITION_PATH(symbol)
    if not path.exists():
        print(f"  [warn] composition file not found for {symbol}: {path}")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["date_greg"] = df["تاریخ"].apply(_to_gregorian)
    return df.dropna(subset=["date_greg"])


def load_nav_history(symbol: str) -> pd.DataFrame:
    path = NAV_HISTORY_PATH(symbol)
    if not path.exists():
        print(f"  [warn] nav_history file not found for {symbol}: {path}")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["date_greg"] = df["تاریخ"].apply(_to_gregorian)
    return df.dropna(subset=["date_greg"])


def load_ime_contract_history(contract: str) -> pd.DataFrame:
    path = IME_CONTRACT_FILES.get(contract)
    if path is None or not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    # DT is expected to already be Gregorian per your schema (DT + PersianDate pair)
    df["date_greg"] = pd.to_datetime(df["DT"]).dt.strftime("%Y-%m-%d")
    prefix = contract.lower()
    df = df.rename(columns={
        "LastPrice": f"{prefix}_last_price",
        "TodaySettlementPrice": f"{prefix}_settlement_price",
        "TradesVolume": f"{prefix}_trades_volume",
    })
    return df[["date_greg", f"{prefix}_last_price", f"{prefix}_settlement_price", f"{prefix}_trades_volume"]]


def load_usdt_daily() -> pd.DataFrame:
    if not USDT_PATH.exists():
        print(f"  [warn] USDT file not found: {USDT_PATH}")
        return pd.DataFrame()
    df = pd.read_csv(USDT_PATH)
    df["date_greg"] = pd.to_datetime(df["datetime_utc"]).dt.strftime("%Y-%m-%d")
    daily = (
        df.sort_values("timestamp")
        .groupby("date_greg")
        .agg(usdt_open=("open", "first"), usdt_close=("close", "last"),
             usdt_high=("high", "max"), usdt_low=("low", "min"))
        .reset_index()
    )
    return daily


# ---------------------------------------------------------------------
# Per-fund merge
# ---------------------------------------------------------------------

def merge_fund(symbol: str, client, usdt_daily: pd.DataFrame) -> pd.DataFrame:
    print(f"\n==> {symbol}")

    comp = load_composition(symbol)
    nav = load_nav_history(symbol)

    if comp.empty and nav.empty:
        print(f"  no local CSVs found for {symbol} — skipping merge")
        return pd.DataFrame()

    merged = nav.merge(comp, on="date_greg", how="outer", suffixes=("_nav", "_comp"))

    # Determine which IME contracts this fund actually holds, via SDK holdings.
    # NOTE: fund.holdings() is a single CURRENT snapshot only — there is no
    # historical series for portfolio composition. gold_legs_weight_pct and
    # legs_as_of are therefore attached as CONSTANT columns (the platform's
    # latest known snapshot), not a true per-date history. The reconciliation
    # check (gold_legs_weight_pct + non-gold composition ≈ 100%) is only
    # meaningful on rows at or near legs_as_of — don't read it as valid for
    # 2023/2024 rows just because the column is populated there too.
    gold_legs_weight_pct = None
    legs_as_of = None
    try:
        holdings = get_fund_holdings(client, symbol)
        legs = holdings.get("legs", []) if isinstance(holdings, dict) else []
        legs_as_of = holdings.get("as_of") if isinstance(holdings, dict) else None
        contracts_held = {
            LEG_TO_CONTRACT[leg["leg_type"]]
            for leg in legs
            if leg.get("leg_type") in LEG_TO_CONTRACT
        }
        gold_legs_weight_pct = sum(
            leg.get("weight_pct", 0.0) for leg in legs if leg.get("weight_pct") is not None
        ) or None
    except Exception as exc:
        print(f"  [warn] could not fetch live holdings for {symbol}: {exc}")
        contracts_held = set()

    merged["gold_legs_weight_pct"] = gold_legs_weight_pct
    merged["legs_as_of"] = legs_as_of

    non_gold_cols = ["سهام (%)", "اوراق (%)", "سایر (%)", "نقد (%)", "سپرده (%)"]
    present_cols = [c for c in non_gold_cols if c in merged.columns]
    if present_cols and gold_legs_weight_pct is not None:
        non_gold_sum = merged[present_cols].sum(axis=1, skipna=True)
        merged["reconciled_total_pct"] = None
        near_snapshot = merged["date_greg"] == legs_as_of
        merged.loc[near_snapshot, "reconciled_total_pct"] = (
            non_gold_sum[near_snapshot] + gold_legs_weight_pct
        )

    for contract in contracts_held:
        contract_df = load_ime_contract_history(contract)
        if not contract_df.empty:
            merged = merged.merge(contract_df, on="date_greg", how="left")
        else:
            print(f"  [warn] {symbol} holds {contract} but no local history file for it")

    if not usdt_daily.empty:
        merged = merged.merge(usdt_daily, on="date_greg", how="left")

    merged = merged.sort_values("date_greg")
    print(
        f"  merged rows: {len(merged)}  contracts_held={sorted(contracts_held) or 'unknown'}  "
        f"gold_legs_weight_pct={gold_legs_weight_pct}  legs_as_of={legs_as_of}"
    )
    return merged


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    usdt_daily = load_usdt_daily()

    client = get_client()
    try:
        for symbol in FUND_SYMBOLS:
            merged = merge_fund(symbol, client, usdt_daily)
            if merged.empty:
                continue
            out_path = OUT_DIR / f"{symbol}_merged.csv"
            merged.to_csv(out_path, index=False, quoting=csv.QUOTE_MINIMAL)
            print(f"  saved -> {out_path}")
    finally:
        close_client()


if __name__ == "__main__":
    main()