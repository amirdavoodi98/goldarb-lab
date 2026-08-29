"""Bubble-rank pair rotation (gold-arbitrage ``BubbleRankStrategy``).

Long the cheapest fund vs its own premium window, short the richest.
Runs on each 1s snapshot (same-bar fill). ``window_days`` is a calendar
window over those 1s premiums, not a tick count.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from goldarb.signals.bubble_rank import (
    BUBBLE_RANK_MIN_GAP,
    BUBBLE_RANK_MIN_SAMPLES,
    BUBBLE_RANK_WINDOW_DAYS,
    compute_rankings,
)
from goldarb.simulation.models import Side, decimal_value
from goldarb.strategies.pairs import (
    append_premiums,
    flatten_positions,
    open_pair,
    pair_event,
    premiums_on_snapshot,
    window_values,
)
from goldarb.strategy import Strategy, StrategyContext

BACKTEST_DEFAULT_CAPITAL_PER_SIDE = Decimal("100000000")


class BubbleRankStrategy(Strategy):
    name = "bubble_rank"
    version = "1"

    def __init__(
        self,
        *,
        capital_per_side: Decimal | float | str = BACKTEST_DEFAULT_CAPITAL_PER_SIDE,
        window_days: int = BUBBLE_RANK_WINDOW_DAYS,
        min_samples: int = BUBBLE_RANK_MIN_SAMPLES,
        min_gap: float = BUBBLE_RANK_MIN_GAP,
    ) -> None:
        self.capital_per_side = decimal_value(capital_per_side)
        self.window_days = int(window_days)
        self.min_samples = int(min_samples)
        self.min_gap = float(min_gap)
        self._current_pair: tuple[str, str] | None = None
        self._premiums: dict[str, list[tuple[datetime, float]]] = {}
        self.events: list[dict[str, Any]] = []
        self.last_ranking: dict[str, Any] | None = None

    def on_start(self, ctx: StrategyContext) -> None:
        self._current_pair = None
        if str(ctx.config.get("reset_history", "")).lower() in {"1", "true", "yes"}:
            self._premiums.clear()
            self.events.clear()

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        window = timedelta(days=self.window_days)
        append_premiums(self._premiums, snapshot, window=window)
        present = premiums_on_snapshot(snapshot)
        now = snapshot.timestamp
        live_history = {
            symbol: window_values(self._premiums[symbol], now=now, window=window)
            for symbol in present
            if symbol in self._premiums
        }
        ranking = compute_rankings(
            live_history,
            min_samples=self.min_samples,
            window_days=self.window_days,
            min_gap=self.min_gap,
        )
        self.last_ranking = ranking
        pair = ranking.get("best_pair")
        if not pair or not pair.get("active"):
            if self._current_pair is None:
                return
            prev = self._current_pair
            flatten_positions(ctx, prefix=self.name)
            self._emit(
                ctx,
                event_type="exit_pair",
                long_sym=prev[0],
                short_sym=prev[1],
                gap=None,
                label_fa=f"خروج از جفت {prev[0]}/{prev[1]}",
            )
            self._current_pair = None
            return

        target = (str(pair["long"]), str(pair["short"]))
        gap = pair.get("gap")
        gap_f = float(gap) if gap is not None else None
        label = pair.get("label_fa")
        if target == self._current_pair:
            return

        had_open = self._current_pair is not None
        flatten_positions(ctx, prefix=self.name)
        opened = open_pair(
            ctx,
            target[0],
            target[1],
            capital_per_side=self.capital_per_side,
            prefix=self.name,
        )
        if opened:
            self._current_pair = target
            self._emit(
                ctx,
                event_type="rebalance_pair" if had_open else "enter_pair",
                long_sym=target[0],
                short_sym=target[1],
                gap=gap_f,
                label_fa=str(label) if label else None,
            )
        else:
            self._current_pair = None

    def _emit(
        self,
        ctx: StrategyContext,
        *,
        event_type: str,
        long_sym: str | None,
        short_sym: str | None,
        gap: float | None,
        label_fa: str | None,
    ) -> None:
        event = pair_event(
            event_type=event_type,
            long_sym=long_sym,
            short_sym=short_sym,
            gap=gap,
            label_fa=label_fa,
        )
        event["event_id"] = "" if ctx.market is None else ctx.market.event_id
        event["timestamp"] = ctx.clock.isoformat()
        self.events.append(event)
        extra = {
            "type": event_type,
            "long": long_sym or "",
            "short": short_sym or "",
            "gap": "" if gap is None else str(gap),
            "label_fa": label_fa or "",
        }
        if long_sym:
            ctx.emit_signal(symbol=long_sym, side=Side.BUY, extra=extra)
        elif short_sym:
            ctx.emit_signal(symbol=short_sym, side=Side.SELL, extra=extra)
