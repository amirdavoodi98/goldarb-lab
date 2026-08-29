"""Long-only moving-average band strategy for ``LocalSimulator``.

The simulator stays a paper broker. ``MaBandStrategy`` owns the signal;
engines inject snapshots and the strategy submits MARKET orders with stable
``client_order_id`` values.

Rules:
- Ignore signals until ``window`` closes are available.
- BUY when close < SMA * (1 - buy_band) and the account is flat.
- SELL when close > SMA * (1 + sell_band) and the account is long.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from goldarb.data import (
    HistoricalDataProvider,
    snapshot_close,
    snapshots_from_bars,
    snapshots_from_closes,
)
from goldarb.engine import BacktestEngine, RunConfig, SimulationLoop
from goldarb.execution import NoLatency, NoSlippage
from goldarb.simulation import Fill, LocalSimulator, Order, Portfolio
from goldarb.strategies.ma_band import (
    MaBandSignal,
    MaBandStrategy,
    MaBandTick,
    ma_band_side,
)

__all__ = [
    "MaBandEngine",
    "MaBandResult",
    "MaBandSignal",
    "MaBandTick",
    "ma_band_side",
    "run_ma_band",
    "snapshot_close",
    "snapshots_from_bars",
    "snapshots_from_closes",
]


@dataclass
class MaBandResult:
    account_id: str
    portfolio: Portfolio
    signals: list[MaBandSignal] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)


class MaBandEngine:
    """Incremental MA-band trader; call ``on_snapshot`` as live bars arrive."""

    def __init__(
        self,
        *,
        simulator: LocalSimulator,
        account_id: str,
        symbol: str = "طلا",
        window: int = 3,
        buy_band: Decimal | float | str = "0.02",
        sell_band: Decimal | float | str = "0.02",
        quantity: Decimal | float | str = "10",
    ) -> None:
        self.simulator = simulator
        self.account_id = account_id
        self.symbol = symbol
        self.window = window
        self.buy_band = buy_band
        self.sell_band = sell_band
        self.quantity = quantity
        self.strategy = MaBandStrategy(
            symbol=symbol,
            window=window,
            buy_band=buy_band,
            sell_band=sell_band,
            quantity=quantity,
        )
        self._loop = SimulationLoop(
            broker=simulator,
            account_id=account_id,
            strategy=self.strategy,
            slippage=NoSlippage(),
            latency=NoLatency(),
        )

    @property
    def signals(self) -> list[MaBandSignal]:
        return self.strategy.signals

    def on_snapshot(self, snapshot):
        self._loop.process(snapshot)
        return self.strategy.last_tick

    def result(self) -> MaBandResult:
        return MaBandResult(
            account_id=self.account_id,
            portfolio=self.simulator.portfolio(self.account_id),
            signals=self.strategy.signals,
            orders=self.simulator.list_orders(self.account_id),
            fills=self.simulator.list_fills(self.account_id),
        )


def run_ma_band(
    snapshots: Sequence,
    *,
    simulator: LocalSimulator,
    account_id: str,
    symbol: str = "طلا",
    window: int = 3,
    buy_band: Decimal | float | str = "0.02",
    sell_band: Decimal | float | str = "0.02",
    quantity: Decimal | float | str = "10",
) -> MaBandResult:
    """Replay snapshots through ``BacktestEngine`` and trade the MA band."""
    strategy = MaBandStrategy(
        symbol=symbol,
        window=window,
        buy_band=buy_band,
        sell_band=sell_band,
        quantity=quantity,
    )
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider(snapshots),
        RunConfig(
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            account_id=account_id,
            label="ma-band",
        ),
        simulator=simulator,
    )
    return MaBandResult(
        account_id=account_id,
        portfolio=result.portfolio,
        signals=strategy.signals,
        orders=result.orders,
        fills=result.fills,
    )
