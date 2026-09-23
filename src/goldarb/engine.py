"""Backtest and live-simulation engines sharing one event loop.

The strategy never sees the data source or broker type. Both engines feed
``LocalSimulator`` (or any ``PaperBroker``) after applying slippage and latency.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from .data import DataProvider
from .execution import (
    Broker,
    ExecutionDriver,
    FeeModel,
    LatencyModel,
    LocalFeedExecution,
    NoLatency,
    NoSlippage,
    PercentFee,
    SlippageModel,
)
from .simulation.engine import ZERO
from .simulation.local import LocalSimulator
from .simulation.models import (
    Fill,
    MarketSnapshot,
    Order,
    OrderStatus,
    Portfolio,
    decimal_value,
)
from .strategy import Strategy, StrategyContext

OnEvent = Callable[[str, StrategyContext], None]


@dataclass(frozen=True)
class RunConfig:
    """Serializable backtest / live-simulation configuration."""

    strategy_name: str
    strategy_version: str = "0"
    initial_cash: str = "1000000000"
    fee_rate: str | None = None
    allow_short: bool = False
    label: str = ""
    account_id: str | None = None
    database: str | None = None
    fee_model: str = "PercentFee"
    slippage_model: str = "NoSlippage"
    latency_model: str = "NoLatency"
    fee_config: dict[str, str] = field(default_factory=dict)
    slippage_config: dict[str, str] = field(default_factory=dict)
    latency_config: dict[str, str] = field(default_factory=dict)
    strategy_config: dict[str, str] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: str(uuid4()))

    def snapshot(
        self,
        *,
        fee: FeeModel,
        slippage: SlippageModel,
        latency: LatencyModel,
    ) -> RunConfig:
        return RunConfig(
            strategy_name=self.strategy_name,
            strategy_version=self.strategy_version,
            initial_cash=self.initial_cash,
            fee_rate=str(fee.rate()),
            allow_short=self.allow_short,
            label=self.label,
            account_id=self.account_id,
            database=self.database,
            fee_model=fee.name,
            slippage_model=slippage.name,
            latency_model=latency.name,
            fee_config=dict(fee.config()),
            slippage_config=dict(slippage.config()),
            latency_config=dict(latency.config()),
            strategy_config=dict(self.strategy_config),
            run_id=self.run_id,
        )


@dataclass(frozen=True)
class Metrics:
    total_return: Decimal
    total_pnl: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    max_drawdown: Decimal
    n_trades: int
    n_orders: int
    n_filled_orders: int
    n_signals: int
    fill_rate: Decimal
    total_fees: Decimal
    initial_cash: Decimal
    final_equity: Decimal


@dataclass
class RunResult:
    account_id: str
    portfolio: Portfolio
    orders: list[Order]
    fills: list[Fill]
    equity_history: list[dict[str, str]]
    metrics: Metrics
    config: RunConfig
    signals: list[Any] = field(default_factory=list)
    log: list[Any] = field(default_factory=list)


def compute_metrics(
    *,
    portfolio: Portfolio,
    equity_history: list[dict[str, str]],
    orders: list[Order],
    fills: list[Fill],
    n_signals: int,
    initial_cash: Decimal,
) -> Metrics:
    peak: Decimal | None = None
    max_dd = ZERO
    for point in equity_history:
        equity = decimal_value(point["equity"])
        if peak is None or equity > peak:
            peak = equity
        if peak is not None and peak > ZERO:
            drawdown = (peak - equity) / peak
            if drawdown > max_dd:
                max_dd = drawdown
    filled = [order for order in orders if order.status == OrderStatus.FILLED]
    n_orders = len(orders)
    fill_rate = (Decimal(len(filled)) / Decimal(n_orders)) if n_orders else ZERO
    total_pnl = portfolio.realized_pnl + portfolio.unrealized_pnl - portfolio.fees_paid
    total_return = (portfolio.equity - initial_cash) / initial_cash if initial_cash else ZERO
    return Metrics(
        total_return=total_return,
        total_pnl=total_pnl,
        realized_pnl=portfolio.realized_pnl,
        unrealized_pnl=portfolio.unrealized_pnl,
        max_drawdown=max_dd,
        n_trades=len(fills),
        n_orders=n_orders,
        n_filled_orders=len(filled),
        n_signals=n_signals,
        fill_rate=fill_rate,
        total_fees=portfolio.fees_paid,
        initial_cash=initial_cash,
        final_equity=portfolio.equity,
    )


class SimulationLoop:
    """Shared market → broker → strategy dispatch used by both engines."""

    def __init__(
        self,
        *,
        broker: Broker,
        account_id: str,
        strategy: Strategy,
        slippage: SlippageModel,
        latency: LatencyModel,
        execution: ExecutionDriver | None = None,
        config: dict[str, Any] | None = None,
        on_event: OnEvent | None = None,
    ) -> None:
        self.broker = broker
        self.account_id = account_id
        self.strategy = strategy
        self.slippage = slippage
        self.latency = latency
        self.execution = execution or LocalFeedExecution()
        self.on_event = on_event
        self.ctx = StrategyContext(broker, account_id, config=config)
        self.strategy.on_start(self.ctx)
        self._seen_fill_ids = {fill.id for fill in self.broker.list_fills(self.account_id)}

    def process(self, snapshot: MarketSnapshot) -> None:
        self.ctx.set_market(snapshot)
        self.ctx.record(
            "market",
            {
                "event_id": snapshot.event_id,
                "symbols": ",".join(quote.symbol for quote in snapshot.quotes),
            },
        )
        # Execution slippage/latency belong on the local paper order path
        # (LocalPaperBroker pipeline), not on market snapshots here.
        self.execution.on_market(self.broker, snapshot)
        self._notify_new_fills()
        self.strategy.on_market_data(self.ctx)
        self._notify_new_fills()
        if self.on_event is not None:
            self.on_event("tick", self.ctx)

    def finish(self) -> None:
        self.strategy.on_stop(self.ctx)
        if self.on_event is not None:
            self.on_event("stop", self.ctx)

    def _notify_new_fills(self) -> None:
        for fill in self.broker.list_fills(self.account_id):
            if fill.id in self._seen_fill_ids:
                continue
            self._seen_fill_ids.add(fill.id)
            self.ctx.record(
                "fill",
                {
                    "fill_id": fill.id,
                    "order_id": fill.order_id,
                    "quantity": str(fill.quantity),
                    "price": str(fill.price),
                    "fee": str(fill.fee),
                },
            )
            self.strategy.on_fill(self.ctx, fill)


class SimulationEngine:
    """Run a strategy over a data provider against a paper broker."""

    def run(
        self,
        strategy: Strategy,
        provider: DataProvider,
        config: RunConfig,
        *,
        simulator: Broker | None = None,
        fee: FeeModel | None = None,
        slippage: SlippageModel | None = None,
        latency: LatencyModel | None = None,
        execution: ExecutionDriver | None = None,
        on_event: OnEvent | None = None,
    ) -> RunResult:
        fee_model = fee or PercentFee(config.fee_rate or "0.0005")
        slippage_model = slippage or NoSlippage()
        latency_model = latency or NoLatency()
        recorded = config.snapshot(fee=fee_model, slippage=slippage_model, latency=latency_model)
        own = False
        broker = simulator
        if broker is None:
            broker = LocalSimulator(
                config.database or ":memory:",
                fee=fee_model,
                slippage=slippage_model,
                latency=latency_model,
            )
            own = True
        elif hasattr(broker, "configure_execution"):
            broker.configure_execution(
                fee=fee_model,
                slippage=slippage_model,
                latency=latency_model,
            )
        try:
            account_id = config.account_id
            if account_id is None:
                account = broker.create_account(
                    initial_cash=config.initial_cash,
                    fee_rate=fee_model.rate(),
                    allow_short=config.allow_short,
                    label=config.label or strategy.name,
                )
                account_id = account.id
            else:
                account = broker.get_account(account_id)
            ctx_config = {
                "run_id": recorded.run_id,
                "strategy_name": strategy.name,
                "strategy_version": getattr(strategy, "version", recorded.strategy_version),
                **recorded.strategy_config,
            }
            loop = SimulationLoop(
                broker=broker,
                account_id=account_id,
                strategy=strategy,
                slippage=slippage_model,
                latency=latency_model,
                execution=execution,
                config=ctx_config,
                on_event=on_event,
            )
            for snapshot in _iter_events(provider):
                loop.process(snapshot)
            if hasattr(broker, "settle_delayed_orders"):
                broker.settle_delayed_orders()
            loop.finish()
            portfolio = broker.portfolio(account_id)
            orders = broker.list_orders(account_id)
            fills = broker.list_fills(account_id)
            history = broker.equity_history(account_id)
            metrics = compute_metrics(
                portfolio=portfolio,
                equity_history=history,
                orders=orders,
                fills=fills,
                n_signals=len(loop.ctx.signals),
                initial_cash=account.initial_cash,
            )
            return RunResult(
                account_id=account_id,
                portfolio=portfolio,
                orders=orders,
                fills=fills,
                equity_history=history,
                metrics=metrics,
                config=recorded,
                signals=list(loop.ctx.signals),
                log=list(loop.ctx.log),
            )
        finally:
            if own:
                broker.close()


class BacktestEngine(SimulationEngine):
    """Historical replay. ``provider.events()`` is finite and ordered."""


class LiveSimulationEngine(SimulationEngine):
    """Live paper loop. Typically paired with ``LiveDataProvider``."""


def _iter_events(provider: DataProvider) -> Iterator[MarketSnapshot]:
    return provider.events()


def memory_simulator(path: str | Path | None = None) -> LocalSimulator:
    return LocalSimulator(path or ":memory:")
