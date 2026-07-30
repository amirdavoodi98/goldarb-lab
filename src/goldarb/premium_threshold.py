"""Offline ``premium_threshold`` backtest (Lab F-10 template, long-only).

Rules (defaults match platform Lab):
- Enter long when premium ≤ ``buy_lte`` (−2%).
- Exit when held premium ≥ ``sell_gte`` (+2%).
- Fill at bar close; default ``fill_mode="next_bar"``.
- Size: ``capital_per_side / close`` units per entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

FillMode = Literal["next_bar", "same_bar"]


def bar_close(row: dict[str, Any]) -> float | None:
    for key in ("close", "close_price"):
        val = row.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None


def bar_premium(row: dict[str, Any]) -> float | None:
    """Prefer ``premium_discount_pct``; else (close − nav) / nav × 100."""
    raw = row.get("premium_discount_pct")
    if raw is None:
        raw = row.get("premium")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    close = bar_close(row)
    nav = row.get("nav_price")
    if close is None or nav is None:
        return None
    try:
        nav_f = float(nav)
    except (TypeError, ValueError):
        return None
    if nav_f <= 0:
        return None
    return round((close - nav_f) / nav_f * 100.0, 4)


def bar_time(row: dict[str, Any]) -> str:
    return str(row.get("bar_at") or row.get("date") or "")


@dataclass
class TradeEvent:
    kind: str  # enter_long | exit_long
    bar_at: str
    premium: float | None
    price: float
    qty: float
    fee: float


@dataclass
class PremiumThresholdResult:
    return_pct: float
    final_equity: float
    initial_cash: float
    max_drawdown_pct: float
    n_bars: int
    n_trades: int  # completed round-trips (exit count)
    events: list[TradeEvent] = field(default_factory=list)
    equity_curve: list[tuple[str, float]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "return_pct": round(self.return_pct, 4),
            "final_equity": round(self.final_equity, 2),
            "initial_cash": self.initial_cash,
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "n_bars": self.n_bars,
            "n_trades": self.n_trades,
            "n_events": len(self.events),
        }


def run_premium_threshold(
    bars: Sequence[dict[str, Any]],
    *,
    buy_lte: float = -2.0,
    sell_gte: float = 2.0,
    capital_per_side: float = 100_000_000.0,
    initial_cash: float = 1_000_000_000.0,
    fee_rate: float = 0.0005,
    fill_mode: FillMode = "next_bar",
) -> PremiumThresholdResult:
    """
    Run long-only premium threshold on a single-symbol bar series.

    ``bars`` must be time-sorted ascending and include close + premium (or NAV).
    """
    if fill_mode not in {"next_bar", "same_bar"}:
        raise ValueError("fill_mode must be 'next_bar' or 'same_bar'")

    cash = float(initial_cash)
    qty = 0.0
    long = False
    pending: tuple[str, float] | None = None  # ("BUY"|"SELL", qty)
    events: list[TradeEvent] = []
    equity_curve: list[tuple[str, float]] = []
    peak = float(initial_cash)
    max_dd = 0.0
    exits = 0

    def mark(px: float | None) -> float:
        if long and px is not None:
            return cash + qty * px
        return cash

    def apply_fill(side: str, fill_qty: float, px: float, t: str, prem: float | None) -> None:
        nonlocal cash, qty, long, exits
        if side == "BUY":
            fee = fill_qty * px * fee_rate
            cash -= fill_qty * px + fee
            qty = fill_qty
            long = True
            events.append(
                TradeEvent("enter_long", t, prem, px, fill_qty, fee)
            )
        else:
            fee = fill_qty * px * fee_rate
            cash += fill_qty * px - fee
            events.append(
                TradeEvent("exit_long", t, prem, px, fill_qty, fee)
            )
            qty = 0.0
            long = False
            exits += 1

    for row in bars:
        t = bar_time(row)
        px = bar_close(row)
        prem = bar_premium(row)

        if pending is not None and px is not None:
            side, fill_qty = pending
            apply_fill(side, fill_qty, px, t, prem)
            pending = None

        order: tuple[str, float] | None = None
        if px is not None and px > 0:
            if long:
                if prem is not None and prem >= sell_gte:
                    order = ("SELL", qty)
            else:
                if prem is not None and prem <= buy_lte:
                    order = ("BUY", capital_per_side / px)

        if order is not None:
            if fill_mode == "same_bar" and px is not None:
                apply_fill(order[0], order[1], px, t, prem)
            else:
                # next_bar: queue; if already pending, replace (Lab keeps latest intent)
                pending = order
                # optimistic bookkeeping for signal-time state (matches one-position Lab)
                if order[0] == "SELL":
                    # stay marked long until fill; pending sell
                    pass
                else:
                    # stay flat until fill
                    pass

        eq = mark(px)
        equity_curve.append((t, eq))
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak * 100.0
            if dd > max_dd:
                max_dd = dd

    # Discard pending on last bar (Lab next_bar behavior)
    final_eq = equity_curve[-1][1] if equity_curve else float(initial_cash)
    ret = (final_eq / float(initial_cash) - 1.0) * 100.0 if initial_cash else 0.0
    return PremiumThresholdResult(
        return_pct=ret,
        final_equity=final_eq,
        initial_cash=float(initial_cash),
        max_drawdown_pct=max_dd,
        n_bars=len(bars),
        n_trades=exits,
        events=events,
        equity_curve=equity_curve,
    )
