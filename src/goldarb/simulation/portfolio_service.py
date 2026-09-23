"""Account ledger and portfolio view (cash truth lives on Account)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .engine import ZERO, apply_position_fill
from .models import (
    Account,
    Portfolio,
    Position,
    Quote,
    Side,
)


@dataclass(frozen=True)
class LedgerPosition:
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    realized_pnl: Decimal


@dataclass(frozen=True)
class LedgerState:
    cash: Decimal
    fees_paid: Decimal
    positions: dict[str, LedgerPosition]


@dataclass(frozen=True)
class FillApplication:
    cash: Decimal
    fees_paid: Decimal
    position: LedgerPosition


class PortfolioService:
    """Pure ledger math — no persistence, no order mutation."""

    def apply_fill(
        self,
        state: LedgerState,
        *,
        symbol: str,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
    ) -> FillApplication:
        current = state.positions.get(
            symbol,
            LedgerPosition(symbol=symbol, quantity=ZERO, average_cost=ZERO, realized_pnl=ZERO),
        )
        signed_notional = quantity * price
        if side == Side.BUY:
            cash = state.cash - signed_notional - fee
        else:
            cash = state.cash + signed_notional - fee
        if cash < ZERO:
            raise ValueError("insufficient_cash")
        result = apply_position_fill(
            current_quantity=current.quantity,
            average_cost=current.average_cost,
            side=side,
            fill_quantity=quantity,
            fill_price=price,
        )
        position = LedgerPosition(
            symbol=symbol,
            quantity=result.quantity,
            average_cost=result.average_cost,
            realized_pnl=current.realized_pnl + result.realized_delta,
        )
        return FillApplication(
            cash=cash,
            fees_paid=state.fees_paid + fee,
            position=position,
        )

    def snapshot(
        self,
        account: Account,
        positions: dict[str, LedgerPosition],
        marks: dict[str, Quote | None],
        *,
        as_of: str | None,
    ) -> Portfolio:
        items: list[Position] = []
        realized = ZERO
        unrealized = ZERO
        market_value = ZERO
        for symbol in sorted(positions):
            row = positions[symbol]
            mark = _mark(marks.get(symbol))
            item_unrealized = (mark - row.average_cost) * row.quantity if mark is not None else ZERO
            item_value = row.quantity * mark if mark is not None else ZERO
            realized += row.realized_pnl
            unrealized += item_unrealized
            market_value += item_value
            items.append(
                Position(
                    symbol=symbol,
                    quantity=row.quantity,
                    average_cost=row.average_cost,
                    realized_pnl=row.realized_pnl,
                    mark_price=mark,
                    unrealized_pnl=item_unrealized,
                    market_value=item_value,
                )
            )
        return Portfolio(
            account_id=account.id,
            cash=account.cash,
            equity=account.cash + market_value,
            fees_paid=account.fees_paid,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            positions=tuple(items),
            as_of=as_of,
        )


def _mark(quote: Quote | None) -> Decimal | None:
    if quote is None:
        return None
    if quote.bid is not None and quote.ask is not None and quote.bid > ZERO and quote.ask > ZERO:
        return (quote.bid + quote.ask) / Decimal(2)
    return quote.last if quote.last is not None and quote.last > ZERO else None
