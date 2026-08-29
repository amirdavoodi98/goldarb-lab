"""Pair z-score relative-value (gold-arbitrage ``PairZScoreStrategy``).

Long the cheap leg / short the rich leg of a fixed fund pair when
``|z|`` of the premium spread exceeds the threshold.

Runs on each 1s snapshot. ``window_days`` is a calendar window over
same-second spreads, not a tick count.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from goldarb.data import snapshot_close
from goldarb.signals.pair_spread import (
    PAIR_SPREAD_DEFAULT_WINDOW,
    PAIR_SPREAD_MIN_SAMPLES,
    PAIR_SPREAD_Z_THRESHOLD,
    compute_pair_spread_stats,
)
from goldarb.simulation.models import Side, decimal_value
from goldarb.strategies.pairs import (
    flatten_positions,
    open_pair,
    pair_event,
    snapshot_premium,
)
from goldarb.strategy import Strategy, StrategyContext

BACKTEST_DEFAULT_CAPITAL_PER_SIDE = Decimal("100000000")


class PairZScoreStrategy(Strategy):
    name = "pair_zscore"
    version = "1"

    def __init__(
        self,
        *,
        capital_per_side: Decimal | float | str = BACKTEST_DEFAULT_CAPITAL_PER_SIDE,
        fund_a: str = "طلا",
        fund_b: str = "زر",
        window_days: int = PAIR_SPREAD_DEFAULT_WINDOW,
        min_samples: int = PAIR_SPREAD_MIN_SAMPLES,
        z_threshold: float = PAIR_SPREAD_Z_THRESHOLD,
    ) -> None:
        self.capital_per_side = decimal_value(capital_per_side)
        self.fund_a = str(fund_a)
        self.fund_b = str(fund_b)
        self.window_days = int(window_days)
        self.min_samples = int(min_samples)
        self.z_threshold = float(z_threshold)
        self._current_pair: tuple[str, str] | None = None
        self._spreads: list[tuple[datetime, float]] = []
        self.events: list[dict[str, Any]] = []
        self.last_status: str | None = None
        self.last_stats: dict[str, Any] | None = None

    def on_start(self, ctx: StrategyContext) -> None:
        self._current_pair = None
        if str(ctx.config.get("reset_history", "")).lower() in {"1", "true", "yes"}:
            self._spreads.clear()
            self.events.clear()

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        prem_a = snapshot_premium(snapshot, self.fund_a)
        prem_b = snapshot_premium(snapshot, self.fund_b)
        if prem_a is not None and prem_b is not None:
            spread = (snapshot.timestamp, round(float(prem_a) - float(prem_b), 6))
            if self._spreads and snapshot.timestamp <= self._spreads[-1][0]:
                if self._spreads[-1][0] == snapshot.timestamp:
                    self._spreads[-1] = spread
            else:
                self._spreads.append(spread)
            cutoff = snapshot.timestamp - timedelta(days=self.window_days)
            if self.window_days > 0:
                keep = 0
                for index, (stamp, _) in enumerate(self._spreads):
                    if stamp >= cutoff:
                        keep = index
                        break
                else:
                    keep = len(self._spreads)
                if keep:
                    del self._spreads[:keep]
        series = self._spread_series(snapshot.timestamp)
        long_px = snapshot_close(snapshot, self.fund_a)
        short_px = snapshot_close(snapshot, self.fund_b)
        stats = compute_pair_spread_stats(
            fund_a=self.fund_a,
            fund_b=self.fund_b,
            series=series,
            premium_a=snapshot_premium(snapshot, self.fund_a),
            premium_b=snapshot_premium(snapshot, self.fund_b),
            price_a=None if long_px is None else float(long_px),
            price_b=None if short_px is None else float(short_px),
            window_days=self.window_days,
            min_samples=self.min_samples,
            z_threshold=self.z_threshold,
        )
        self.last_stats = stats
        self.last_status = str(stats.get("status") or "")
        signal = stats.get("pair_signal") or {}
        active = bool(signal.get("active"))

        if not active:
            if self._current_pair is None:
                return
            prev = self._current_pair
            flatten_positions(ctx, prefix=self.name)
            self._emit(
                ctx,
                event_type="exit_pair",
                long_sym=prev[0],
                short_sym=prev[1],
                z_score=stats.get("z_score"),
                label_fa=f"خروج از جفت {prev[0]}/{prev[1]}",
            )
            self._current_pair = None
            return

        target = (str(signal["long"]), str(signal["short"]))
        z_score = stats.get("z_score")
        z_f = float(z_score) if z_score is not None else None
        label = signal.get("detail_fa") or signal.get("label_fa")
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
                z_score=z_f,
                label_fa=str(label) if label else None,
            )
        else:
            self._current_pair = None

    def _spread_series(self, now: datetime | None = None) -> list[float]:
        if now is None:
            if not self._spreads:
                return []
            now = self._spreads[-1][0]
        cutoff = now - timedelta(days=self.window_days)
        if self.window_days <= 0:
            return [value for _, value in self._spreads]
        return [value for stamp, value in self._spreads if stamp >= cutoff]

    def _emit(
        self,
        ctx: StrategyContext,
        *,
        event_type: str,
        long_sym: str | None,
        short_sym: str | None,
        z_score: float | None,
        label_fa: str | None,
    ) -> None:
        event = pair_event(
            event_type=event_type,
            long_sym=long_sym,
            short_sym=short_sym,
            gap=z_score,
            label_fa=label_fa,
            extra={"z_score": z_score},
        )
        event["event_id"] = "" if ctx.market is None else ctx.market.event_id
        event["timestamp"] = ctx.clock.isoformat()
        self.events.append(event)
        extra = {
            "type": event_type,
            "long": long_sym or "",
            "short": short_sym or "",
            "z_score": "" if z_score is None else str(z_score),
            "label_fa": label_fa or "",
        }
        if long_sym:
            ctx.emit_signal(symbol=long_sym, side=Side.BUY, extra=extra)
        elif short_sym:
            ctx.emit_signal(symbol=short_sym, side=Side.SELL, extra=extra)
