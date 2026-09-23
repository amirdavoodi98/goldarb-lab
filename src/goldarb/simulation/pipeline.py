"""Order-path execution: match → slip → fee → portfolio deltas (no commits)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..execution import FeeModel, LatencyModel, PercentFee, SlippageModel
from .engine import ZERO
from .matching import MatchingEngine
from .models import Fill, MatchResult, Order, Quote, Side
from .portfolio_service import FillApplication, LedgerState, PortfolioService


@dataclass(frozen=True)
class PipelineFill:
    fill: Fill
    ledger: FillApplication
    match: MatchResult


@dataclass(frozen=True)
class PipelineResult:
    fills: tuple[PipelineFill, ...]
    match: MatchResult


class ExecutionPipeline:
    """
    Order → MatchingEngine → SlippageModel → FeeModel → PortfolioService

    SubmitLatency is applied by the broker before acceptance; this pipeline
    runs only on working (accepted) orders.
    """

    def __init__(
        self,
        matching: MatchingEngine,
        *,
        slippage: SlippageModel,
        fee: FeeModel,
        portfolio: PortfolioService | None = None,
    ) -> None:
        self.matching = matching
        self.slippage = slippage
        self.fee = fee
        self.portfolio = portfolio or PortfolioService()

    def run(
        self,
        order: Order,
        *,
        quote: Quote | None,
        available_depth: Decimal | None,
        ledger: LedgerState,
        allow_short: bool,
        market_event_id: str,
        market_timestamp: datetime,
        execution_timestamp: datetime | None = None,
        position_qty: Decimal | None = None,
        fee_rate: Decimal | None = None,
    ) -> PipelineResult:
        current_position = (
            position_qty
            if position_qty is not None
            else ledger.positions.get(order.symbol).quantity  # type: ignore[union-attr]
            if order.symbol in ledger.positions
            else ZERO
        )
        rate = self.fee.rate() if fee_rate is None else fee_rate
        match = self.matching.match_order(
            order,
            quote=quote,
            available_depth=available_depth,
            cash=ledger.cash,
            fee_rate=rate,
            current_position=current_position,
            allow_short=allow_short,
        )
        if match.proposed is None:
            return PipelineResult((), match)

        raw = match.proposed.raw_match_price
        qty = match.proposed.quantity
        price = self.slippage.adjust_fill_price(
            raw_match_price=raw,
            side=order.side,
            quote=quote,
        )
        from .engine import fee_for

        fee_amount = fee_for(qty, price, rate)
        application = self.portfolio.apply_fill(
            ledger,
            symbol=order.symbol,
            side=order.side,
            quantity=qty,
            price=price,
            fee=fee_amount,
        )
        stamp = (execution_timestamp or market_timestamp).isoformat()
        fill = Fill(
            id=str(uuid.uuid4()),
            order_id=order.id,
            market_event_id=market_event_id,
            quantity=qty,
            price=price,
            fee=fee_amount,
            filled_at=stamp,
            raw_match_price=raw,
            market_timestamp=market_timestamp.isoformat(),
            execution_timestamp=stamp,
        )
        return PipelineResult((PipelineFill(fill, application, match),), match)


def active_after_latency(
    submitted_at: datetime,
    latency: LatencyModel,
) -> datetime:
    return submitted_at + latency.submit_delay()
