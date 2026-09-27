"""In-memory remote venue for tests — owns matching server-side."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

from .engine import ZERO, apply_position_fill, fee_for, floor_quantity
from .models import (
    Account,
    Fill,
    MarketSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Quote,
    Side,
    TimeInForce,
    decimal_value,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class _LedgerPos:
    quantity: Decimal = ZERO
    average_cost: Decimal = ZERO
    realized_pnl: Decimal = ZERO


@dataclass
class InMemoryRemoteVenue:
    """
    Test double for RemoteVenue.

    Matching and fee are applied here only. Client RemoteSimulator must not
    re-apply slippage/fee/latency on ingested fills.
    """

    fee_rate: Decimal = Decimal("0.001")
    allow_short_default: bool = False
    # Optional fixed adverse selection already baked into fill.price on server.
    server_slippage: Decimal = ZERO
    accounts: dict[str, Account] = field(default_factory=dict)
    orders: dict[str, Order] = field(default_factory=dict)
    fills: dict[str, list[Fill]] = field(default_factory=dict)
    positions: dict[str, dict[str, _LedgerPos]] = field(default_factory=dict)
    quotes: dict[str, Quote] = field(default_factory=dict)
    equity: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    by_client: dict[tuple[str, str], str] = field(default_factory=dict)
    event_log: list[str] = field(default_factory=list)

    def set_quote(self, quote: Quote) -> None:
        self.quotes[quote.symbol] = quote

    def apply_market(self, snapshot: MarketSnapshot) -> None:
        """Server-side market update (not used by client feed)."""
        for quote in snapshot.quotes:
            self.quotes[quote.symbol] = quote
        for account_id in list(self.accounts):
            self._match_account(account_id, snapshot.event_id, snapshot.timestamp.isoformat())

    def create_account(
        self,
        *,
        initial_cash: Decimal | float | str,
        label: str = "",
        fee_rate: Decimal | float | str = "0.0005",
        allow_short: bool = False,
        broker: str | None = None,
    ) -> Account:
        cash = decimal_value(initial_cash)
        rate = decimal_value(fee_rate)
        account_id = str(uuid.uuid4())
        stamp = _now()
        account = Account(
            id=account_id,
            label=label,
            status="ACTIVE",
            initial_cash=cash,
            cash=cash,
            fee_rate=rate,
            allow_short=allow_short,
            fees_paid=ZERO,
            created_at=stamp,
            updated_at=stamp,
            broker=str(broker or ""),
        )
        self.accounts[account_id] = account
        self.positions[account_id] = {}
        self.fills[account_id] = []
        self.equity[account_id] = []
        self.event_log.append(f"account:{account_id}")
        return account

    def get_account(self, account_id: str) -> Account:
        return self.accounts[account_id]

    def submit_order(
        self,
        account_id: str,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        broker: str | None = None,
    ) -> Order:
        client_id = client_order_id or str(uuid.uuid4())
        key = (account_id, client_id)
        if key in self.by_client:
            return self.orders[self.by_client[key]]
        stamp = _now()
        order_id = str(uuid.uuid4())
        order = Order(
            id=order_id,
            account_id=account_id,
            client_order_id=client_id,
            symbol=symbol,
            side=Side(str(side).upper()),
            order_type=OrderType(str(order_type).upper()),
            quantity=decimal_value(quantity),
            filled_quantity=ZERO,
            limit_price=None if limit_price is None else decimal_value(limit_price),
            status=OrderStatus.CREATED,
            submitted_at=stamp,
            updated_at=stamp,
            broker=str(broker or ""),
            time_in_force=TimeInForce.DAY,
            created_at=stamp,
            active_at=stamp,
        )
        self.orders[order_id] = order
        self.by_client[key] = order_id
        self.event_log.append(f"submit:{order_id}")
        # Accept immediately (server-side latency already applied by venue contract).
        order = replace(order, status=OrderStatus.ACCEPTED, accepted_at=stamp, updated_at=stamp)
        self.orders[order_id] = order
        self.event_log.append(f"accepted:{order_id}")
        self._match_account(account_id, f"submit:{order_id}", stamp, only=order_id)
        return self.orders[order_id]

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        order = self.orders[order_id]
        if order.account_id != account_id:
            raise KeyError(order_id)
        stamp = _now()
        if order.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }:
            return order
        # Late-fill window: mark cancel pending then confirm after match attempt.
        order = replace(order, status=OrderStatus.CANCEL_PENDING, updated_at=stamp)
        self.orders[order_id] = order
        self.event_log.append(f"cancel_pending:{order_id}")
        self._match_account(account_id, f"cancel:{order_id}", stamp, only=order_id)
        order = self.orders[order_id]
        if order.status == OrderStatus.CANCEL_PENDING:
            order = replace(
                order,
                status=OrderStatus.CANCELLED,
                updated_at=stamp,
                closed_at=stamp,
            )
            self.orders[order_id] = order
            self.event_log.append(f"cancelled:{order_id}")
        return order

    def list_orders(self, account_id: str) -> list[Order]:
        rows = [o for o in self.orders.values() if o.account_id == account_id]
        return sorted(rows, key=lambda item: (item.submitted_at, item.id))

    def list_fills(self, account_id: str) -> list[Fill]:
        return list(self.fills.get(account_id, []))

    def portfolio(self, account_id: str) -> Portfolio:
        account = self.accounts[account_id]
        items: list[Position] = []
        realized = ZERO
        unrealized = ZERO
        value = ZERO
        for symbol, pos in sorted(self.positions.get(account_id, {}).items()):
            quote = self.quotes.get(symbol)
            mark = None
            if quote is not None:
                if quote.bid and quote.ask:
                    mark = (quote.bid + quote.ask) / Decimal(2)
                else:
                    mark = quote.last
            u = (mark - pos.average_cost) * pos.quantity if mark is not None else ZERO
            v = pos.quantity * mark if mark is not None else ZERO
            realized += pos.realized_pnl
            unrealized += u
            value += v
            items.append(
                Position(
                    symbol=symbol,
                    quantity=pos.quantity,
                    average_cost=pos.average_cost,
                    realized_pnl=pos.realized_pnl,
                    mark_price=mark,
                    unrealized_pnl=u,
                    market_value=v,
                )
            )
        return Portfolio(
            account_id=account_id,
            cash=account.cash,
            equity=account.cash + value,
            fees_paid=account.fees_paid,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            positions=tuple(items),
            as_of=account.updated_at,
        )

    def equity_history(self, account_id: str) -> list[dict[str, str]]:
        return list(self.equity.get(account_id, []))

    def push_fill(
        self,
        account_id: str,
        order_id: str,
        *,
        quantity: Decimal | float | str,
        price: Decimal | float | str,
        fee: Decimal | float | str,
        fill_id: str | None = None,
        market_event_id: str = "push",
    ) -> Fill:
        """Inject a server fill (tests late-fill / duplicates)."""
        order = self.orders[order_id]
        qty = decimal_value(quantity)
        px = decimal_value(price)
        fee_amt = decimal_value(fee)
        stamp = _now()
        fill = Fill(
            id=fill_id or str(uuid.uuid4()),
            order_id=order_id,
            market_event_id=market_event_id,
            quantity=qty,
            price=px,
            fee=fee_amt,
            filled_at=stamp,
            raw_match_price=px - self.server_slippage
            if order.side == Side.BUY
            else px + self.server_slippage,
            market_timestamp=stamp,
            execution_timestamp=stamp,
        )
        self._commit_fill(account_id, order, fill)
        return fill

    def _match_account(
        self,
        account_id: str,
        event_id: str,
        stamp: str,
        *,
        only: str | None = None,
    ) -> None:
        account = self.accounts[account_id]
        for order in self.list_orders(account_id):
            if only is not None and order.id != only:
                continue
            if order.status not in {
                OrderStatus.ACCEPTED,
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.CANCEL_PENDING,
            }:
                continue
            quote = self.quotes.get(order.symbol)
            if quote is None:
                if order.order_type == OrderType.MARKET:
                    self.orders[order.id] = replace(
                        order,
                        status=OrderStatus.REJECTED,
                        rejection_code="price_unavailable",
                        updated_at=stamp,
                        closed_at=stamp,
                    )
                continue
            raw = quote.ask if order.side == Side.BUY else quote.bid
            if raw is None or raw <= ZERO:
                raw = quote.last
            if raw is None or raw <= ZERO:
                continue
            if order.order_type == OrderType.LIMIT and order.limit_price is not None:
                crosses = (
                    raw <= order.limit_price
                    if order.side == Side.BUY
                    else raw >= order.limit_price
                )
                if not crosses:
                    continue
            remaining = order.quantity - order.filled_quantity
            depth = quote.ask_size if order.side == Side.BUY else quote.bid_size
            fillable = remaining if depth is None else min(remaining, depth)
            if order.side == Side.BUY:
                unit = raw * (Decimal(1) + account.fee_rate)
                affordable = floor_quantity(account.cash / unit) if unit > ZERO else ZERO
                fillable = min(fillable, affordable)
                if fillable <= ZERO:
                    if order.filled_quantity == ZERO and order.order_type == OrderType.MARKET:
                        self.orders[order.id] = replace(
                            order,
                            status=OrderStatus.REJECTED,
                            rejection_code="insufficient_cash",
                            updated_at=stamp,
                            closed_at=stamp,
                        )
                    continue
            qty = floor_quantity(fillable)
            if qty <= ZERO:
                continue
            # Server applies slippage into execution price once.
            price = raw + self.server_slippage if order.side == Side.BUY else raw - self.server_slippage
            fee_amt = fee_for(qty, price, account.fee_rate)
            fill = Fill(
                id=str(uuid.uuid4()),
                order_id=order.id,
                market_event_id=event_id,
                quantity=qty,
                price=price,
                fee=fee_amt,
                filled_at=stamp,
                raw_match_price=raw,
                market_timestamp=stamp,
                execution_timestamp=stamp,
            )
            self._commit_fill(account_id, order, fill)

    def _commit_fill(self, account_id: str, order: Order, fill: Fill) -> None:
        # Idempotent on fill id
        existing_ids = {item.id for item in self.fills.get(account_id, [])}
        if fill.id in existing_ids:
            return
        account = self.accounts[account_id]
        pos = self.positions[account_id].get(order.symbol, _LedgerPos())
        notional = fill.quantity * fill.price
        cash = (
            account.cash - notional - fill.fee
            if order.side == Side.BUY
            else account.cash + notional - fill.fee
        )
        result = apply_position_fill(
            current_quantity=pos.quantity,
            average_cost=pos.average_cost,
            side=order.side,
            fill_quantity=fill.quantity,
            fill_price=fill.price,
        )
        self.positions[account_id][order.symbol] = _LedgerPos(
            quantity=result.quantity,
            average_cost=result.average_cost,
            realized_pnl=pos.realized_pnl + result.realized_delta,
        )
        account = replace(
            account,
            cash=cash,
            fees_paid=account.fees_paid + fill.fee,
            updated_at=fill.filled_at,
        )
        self.accounts[account_id] = account
        self.fills.setdefault(account_id, []).append(fill)
        filled = order.filled_quantity + fill.quantity
        if filled >= order.quantity:
            status = OrderStatus.FILLED
            closed = fill.filled_at
        elif order.status == OrderStatus.CANCEL_PENDING:
            status = OrderStatus.CANCEL_PENDING
            closed = None
        else:
            status = OrderStatus.PARTIALLY_FILLED
            closed = None
        self.orders[order.id] = replace(
            order,
            filled_quantity=filled,
            status=status,
            updated_at=fill.filled_at,
            closed_at=closed,
            avg_fill_price=fill.price
            if order.avg_fill_price is None
            else (
                (order.avg_fill_price * order.filled_quantity + fill.price * fill.quantity)
                / filled
            ),
        )
        self.event_log.append(f"fill:{fill.id}")
        port = self.portfolio(account_id)
        self.equity.setdefault(account_id, []).append(
            {
                "event_id": fill.market_event_id,
                "recorded_at": fill.filled_at,
                "cash": str(port.cash),
                "equity": str(port.equity),
                "realized_pnl": str(port.realized_pnl),
                "unrealized_pnl": str(port.unrealized_pnl),
            }
        )
