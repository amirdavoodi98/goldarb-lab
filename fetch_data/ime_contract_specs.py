"""
ime_contract_specs.py — static reference table for IME CDC contract specs.

Addresses roadmap Chunk 3 / report §4 item ۴.۴ (متادیتای قراردادهای IME).
This data does NOT come from the SDK/platform API — it is NOT available
anywhere in fund.py, market.py, or urls.py (confirmed repeatedly earlier
in this project). It comes from IME's own public announcements and
verified educational sources about each specific "پیوسته" (continuous,
no-maturity-date) product — matched by symbol/description to exactly
what the platform's ime_cdc_live()/ime_cdc_stats() contract_code values
actually represent.

IMPORTANT: valid_from dates below are approximate Gregorian conversions
from the sourced Jalali dates — flagged where exact day precision
wasn't independently verified. Do not treat day-level precision as
guaranteed; the month/year is solid, the exact day may be off by 1-2
days depending on calendar conversion edge cases.

Sources (checked 2026-08-12):
  - GoldBar (CD1G0B0001):
      learning.emofid.com/buying-gold-bars-from-the-stock-market
      bashgah.com/blog/gold-certificate
  - GoldCoin (CD1GOC0001, "پیوسته"):
      learning.emofid.com/buy-coins-commodity-exchange
      learning.emofid.com/best-type-gold-investment
  - SilverBar:
      imereport.ir (کالاخبر) — آشنایی با معاملات گواهی سپرده شمش نقره
"""

from __future__ import annotations

from typing import Any

IME_CONTRACT_SPECS: dict[str, dict[str, Any]] = {
    "GoldBar": {
        "contract_code": "GoldBar",
        "exchange_symbol": "CD1G0B0001",
        "underlying_desc_fa": "شمش طلای یک‌کیلوگرمی",
        "certificate_to_gram": 0.1,       # each certificate = 0.1g (۱۰۰ سوت)
        "purity": 995,                     # per-1000; physically delivered bars range 995–999,
                                            # but trading/settlement purity is quoted as 995
        "contract_multiplier": 1,          # price already quoted per certificate (0.1g unit)
        "coin_type": None,                 # not applicable — this is a bullion cert, not a coin
        "currency": "IRR",                 # NOT independently re-verified against SDK output —
                                            # cross-check against a live price before relying on this
        "price_unit": "per_certificate",   # i.e. per 0.1g, not per gram or per kg
        "valid_from": "1401-12",           # Esfand 1401 ≈ Feb/Mar 2023 — month precision only
        "valid_from_gregorian_approx": "2023-03",
        "valid_to": None,                  # ongoing as of research date
        "maturity": "has_maturity_dates",  # unlike GoldCoin's پیوسته product, GoldBar certs
                                            # are tied to specific delivery/maturity cycles
        "source_note": "دارایی پایه شمش یک‌کیلوگرمی؛ تحویل نهایی با عیار تصادفی ۹۹۵ تا ۹۹۹",
    },
    "GoldCoin": {
        "contract_code": "GoldCoin",
        "exchange_symbol": "CD1GOC0001",
        "underlying_desc_fa": "سکه تمام بهار آزادی طرح جدید (امامی)",
        "certificate_to_gram": 8.133,      # each certificate = 1 FULL COIN = 8.133g
                                            # (NOT 0.01 or 0.001 — that ratio applies to a
                                            # DIFFERENT, maturity-dated bank-issued product,
                                            # not this platform's "پیوسته" contract)
        "purity": 900,                     # 22 karat
        "contract_multiplier": 1,          # 1 certificate = 1 coin, no fractional multiplier
        "coin_type": "بهار آزادی طرح جدید",
        "currency": "IRR",                 # NOT independently re-verified — cross-check before relying
        "price_unit": "per_certificate",   # i.e. per full coin
        "valid_from": "1403-02-17",        # 17 Ordibehesht 1403
        "valid_from_gregorian_approx": "2024-05-06",  # approximate — see module docstring caveat
        "valid_to": None,
        "maturity": "no_maturity_date",    # this is the defining feature of the پیوسته product
        "source_note": (
            "گواهی سپرده پیوسته — بدون سررسید، معاملات تا ساعت ۱۸ و شامل روز پنج‌شنبه هم می‌شود "
            "(بر خلاف سایر گواهی‌های سکه که فقط شنبه تا چهارشنبه معامله می‌شوند)"
        ),
    },
    "SilverBar": {
        "contract_code": "SilverBar",
        "exchange_symbol": None,           # not confirmed in sourced material — verify if needed
        "underlying_desc_fa": "شمش نقره یک‌کیلوگرمی",
        "certificate_to_gram": 1.0,        # each certificate = 1g of a 1kg silver bar
        "purity": 999.9,
        "contract_multiplier": 1,
        "coin_type": None,
        "currency": "IRR",                 # NOT independently re-verified — cross-check before relying
        "price_unit": "per_certificate",   # i.e. per gram
        "valid_from": "1403-09",           # Azar 1403 ≈ Nov/Dec 2024 — month precision only
        "valid_from_gregorian_approx": "2024-11",
        "valid_to": None,
        "maturity": "unknown",             # not confirmed in sourced material
        "source_note": (
            "اولین دارایی پایه مشمول مالیات بر ارزش افزوده طبق قانون تامین مالی تولید "
            "و زیرساخت‌ها (اردیبهشت ۱۴۰۳)؛ باید بر روی شمش‌ها نشان تجاری، عیار، وزن و "
            "شماره سریال حک شده باشد"
        ),
    },
}


def get_contract_spec(contract_code: str) -> dict[str, Any]:
    """Look up static specs for a contract_code (GoldBar/GoldCoin/SilverBar)."""
    if contract_code not in IME_CONTRACT_SPECS:
        raise KeyError(
            f"No specs for '{contract_code}'. Known: {list(IME_CONTRACT_SPECS)}"
        )
    return IME_CONTRACT_SPECS[contract_code]


if __name__ == "__main__":
    import json
    print(json.dumps(IME_CONTRACT_SPECS, ensure_ascii=False, indent=2))