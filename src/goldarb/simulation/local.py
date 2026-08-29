"""Offline simulator facade backed by SQLite."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from .engine import ZERO, apply_position_fill, fee_for, match_order
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
    decimal_value,
)
from .storage import SQLiteRepository

_OPEN_STATUSES = (OrderStatus.OPEN.value, OrderStatus.PARTIALLY_FILLED.value)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: Any, default: str = "0") -> Decimal:
    return Decimal(str(default if value is None else value))


class LocalSimulator:
    """Strategy-independent paper broker that never performs network I/O."""

    def __init__(self, path: str | Path) -> None:
        self._repo = SQLiteRepository(path)

    def close(self) -> None:
        self._repo.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def create_account(
        self,
        *,
        initial_cash: Decimal | float | str,
        label: str = "",
        fee_rate: Decimal | float | str = "0.0005",
        allow_short: bool = False,
        account_id: str | None = None,
    ) -> Account:
        cash = decimal_value(initial_cash)
        fee = decimal_value(fee_rate)
        if cash <= ZERO:
            raise ValueError("initial_cash must be positive")
        if fee < ZERO or fee >= Decimal(1):
            raise ValueError("fee_rate must be between 0 and 1")
        identifier = account_id or str(uuid.uuid4())
        stamp = _now()
        with self._repo.transaction() as db:
            db.execute(
                """
                INSERT INTO accounts(
                    id, label, status, initial_cash, cash, fee_rate,
                    allow_short, fees_paid, created_at, updated_at
                ) VALUES (?, ?, 'ACTIVE', ?, ?, ?, ?, '0', ?, ?)
                """,
                (
                    identifier,
                    label[:120],
                    str(cash),
                    str(cash),
                    str(fee),
                    int(allow_short),
                    stamp,
                    stamp,
                ),
            )
        return self.get_account(identifier)

    def get_account(self, account_id: str) -> Account:
        row = self._repo.connection.execute(
            "SELECT * FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown simulation account: {account_id}")
        return Account(
            id=row["id"],
            label=row["label"],
            status=row["status"],
            initial_cash=_decimal(row["initial_cash"]),
            cash=_decimal(row["cash"]),
            fee_rate=_decimal(row["fee_rate"]),
            allow_short=bool(row["allow_short"]),
            fees_paid=_decimal(row["fees_paid"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

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
    ) -> Order:
        side_value = Side(str(side).upper())
        type_value = OrderType(str(order_type).upper())
        qty = decimal_value(quantity)
        limit = None if limit_price is None else decimal_value(limit_price)
        if qty <= ZERO:
            raise ValueError("quantity must be positive")
        if type_value == OrderType.LIMIT and (limit is None or limit <= ZERO):
            raise ValueError("positive limit_price is required for LIMIT orders")
        client_id = client_order_id or str(uuid.uuid4())
        order_id = str(uuid.uuid4())
        stamp = _now()
        with self._repo.transaction() as db:
            account = db.execute(
                "SELECT * FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            if account is None:
                raise KeyError(f"unknown simulation account: {account_id}")
            existing = db.execute(
                "SELECT id FROM orders WHERE account_id=? AND client_order_id=?",
                (account_id, client_id),
            ).fetchone()
            if existing is not None:
                return self._order_from_row(
                    db.execute("SELECT * FROM orders WHERE id=?", (existing["id"],)).fetchone()
                )
            db.execute(
                """
                INSERT INTO orders(
                    id, account_id, client_order_id, symbol, side, order_type,
                    quantity, filled_quantity, limit_price, status,
                    submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '0', ?, 'OPEN', ?, ?)
                """,
                (
                    order_id,
                    account_id,
                    client_id,
                    symbol.strip(),
                    side_value.value,
                    type_value.value,
                    str(qty),
                    _text(limit),
                    stamp,
                    stamp,
                ),
            )
            latest = db.execute(
                "SELECT event_id, timestamp FROM market_events ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if latest is not None:
                self._match_account(db, account_id, latest["event_id"], latest["timestamp"])
                self._record_equity(db, account_id, latest["event_id"], latest["timestamp"])
        return self.get_order(account_id, order_id)

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        stamp = _now()
        with self._repo.transaction() as db:
            cursor = db.execute(
                """
                UPDATE orders SET status='CANCELLED', updated_at=?
                WHERE id=? AND account_id=? AND status IN ('OPEN', 'PARTIALLY_FILLED')
                """,
                (stamp, order_id, account_id),
            )
            if cursor.rowcount == 0:
                row = db.execute(
                    "SELECT * FROM orders WHERE id=? AND account_id=?",
                    (order_id, account_id),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown order: {order_id}")
        return self.get_order(account_id, order_id)

    def feed(self, snapshot: MarketSnapshot) -> bool:
        """Persist a snapshot and match all accounts; duplicate event IDs are no-ops."""
        if not snapshot.event_id.strip():
            raise ValueError("event_id is required")
        timestamp = snapshot.timestamp
        if timestamp.tzinfo is None:
            raise ValueError("snapshot timestamp must be timezone-aware")
        stamp = timestamp.isoformat()
        with self._repo.transaction() as db:
            if db.execute(
                "SELECT 1 FROM market_events WHERE event_id=?", (snapshot.event_id,)
            ).fetchone():
                return False
            latest = db.execute(
                "SELECT timestamp FROM market_events ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if latest is not None and datetime.fromisoformat(latest["timestamp"]) > timestamp:
                raise ValueError("snapshot timestamps must be monotonic")
            db.execute(
                "INSERT INTO market_events(event_id, timestamp) VALUES (?, ?)",
                (snapshot.event_id, stamp),
            )
            for quote in snapshot.quotes:
                db.execute(
                    """
                    INSERT INTO quotes(
                        symbol, event_id, timestamp, bid, ask, last, bid_size, ask_size
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        event_id=excluded.event_id, timestamp=excluded.timestamp,
                        bid=excluded.bid, ask=excluded.ask, last=excluded.last,
                        bid_size=excluded.bid_size, ask_size=excluded.ask_size
                    """,
                    (
                        quote.symbol,
                        snapshot.event_id,
                        stamp,
                        _text(quote.bid),
                        _text(quote.ask),
                        _text(quote.last),
                        _text(quote.bid_size),
                        _text(quote.ask_size),
                    ),
                )
            accounts = db.execute(
                "SELECT id FROM accounts WHERE status='ACTIVE' ORDER BY created_at, id"
            ).fetchall()
            for account in accounts:
                self._match_account(db, account["id"], snapshot.event_id, stamp)
                self._record_equity(db, account["id"], snapshot.event_id, stamp)
        return True

    def get_order(self, account_id: str, order_id: str) -> Order:
        row = self._repo.connection.execute(
            "SELECT * FROM orders WHERE id=? AND account_id=?", (order_id, account_id)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown order: {order_id}")
        return self._order_from_row(row)

    def list_orders(self, account_id: str) -> list[Order]:
        rows = self._repo.connection.execute(
            "SELECT * FROM orders WHERE account_id=? ORDER BY submitted_at, id",
            (account_id,),
        ).fetchall()
        return [self._order_from_row(row) for row in rows]

    def list_fills(self, account_id: str) -> list[Fill]:
        rows = self._repo.connection.execute(
            """
            SELECT fills.* FROM fills
            JOIN orders ON orders.id=fills.order_id
            WHERE orders.account_id=?
            ORDER BY fills.filled_at, fills.id
            """,
            (account_id,),
        ).fetchall()
        return [
            Fill(
                id=row["id"],
                order_id=row["order_id"],
                market_event_id=row["market_event_id"],
                quantity=_decimal(row["quantity"]),
                price=_decimal(row["price"]),
                fee=_decimal(row["fee"]),
                filled_at=row["filled_at"],
            )
            for row in rows
        ]

    def portfolio(self, account_id: str) -> Portfolio:
        account = self.get_account(account_id)
        rows = self._repo.connection.execute(
            """
            SELECT positions.*, quotes.bid, quotes.ask, quotes.last
            FROM positions LEFT JOIN quotes ON quotes.symbol=positions.symbol
            WHERE positions.account_id=? ORDER BY positions.symbol
            """,
            (account_id,),
        ).fetchall()
        positions: list[Position] = []
        realized = ZERO
        unrealized = ZERO
        market_value = ZERO
        for row in rows:
            quantity = _decimal(row["quantity"])
            average = _decimal(row["average_cost"])
            mark = self._mark_from_row(row)
            item_unrealized = (
                (mark - average) * quantity if mark is not None else ZERO
            )
            item_value = quantity * mark if mark is not None else ZERO
            item_realized = _decimal(row["realized_pnl"])
            realized += item_realized
            unrealized += item_unrealized
            market_value += item_value
            positions.append(
                Position(
                    symbol=row["symbol"],
                    quantity=quantity,
                    average_cost=average,
                    realized_pnl=item_realized,
                    mark_price=mark,
                    unrealized_pnl=item_unrealized,
                    market_value=item_value,
                )
            )
        return Portfolio(
            account_id=account_id,
            cash=account.cash,
            equity=account.cash + market_value,
            fees_paid=account.fees_paid,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            positions=tuple(positions),
            as_of=self._repo.connection.execute(
                "SELECT last_market_at FROM accounts WHERE id=?", (account_id,)
            ).fetchone()["last_market_at"],
        )

    def equity_history(self, account_id: str) -> list[dict[str, str]]:
        return [
            dict(row)
            for row in self._repo.connection.execute(
                """
                SELECT event_id, recorded_at, cash, equity, realized_pnl, unrealized_pnl
                FROM equity_points WHERE account_id=? ORDER BY recorded_at, event_id
                """,
                (account_id,),
            ).fetchall()
        ]

    def _match_account(
        self, db: Any, account_id: str, event_id: str, timestamp: str
    ) -> None:
        account = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        orders = db.execute(
            """
            SELECT * FROM orders
            WHERE account_id=? AND status IN ('OPEN', 'PARTIALLY_FILLED')
            ORDER BY submitted_at, id
            """,
            (account_id,),
        ).fetchall()
        depth: dict[tuple[str, str], Decimal | None] = {}
        for row in orders:
            quote_row = db.execute(
                "SELECT * FROM quotes WHERE symbol=?", (row["symbol"],)
            ).fetchone()
            quote = self._quote_from_row(quote_row)
            side = Side(row["side"])
            key = (row["symbol"], side.value)
            if key not in depth:
                available = (
                    quote.ask_size
                    if quote and side == Side.BUY
                    else quote.bid_size
                    if quote
                    else None
                )
                if available is not None:
                    consumed_rows = db.execute(
                        """
                        SELECT fills.quantity FROM fills
                        JOIN orders ON orders.id=fills.order_id
                        WHERE orders.account_id=? AND orders.symbol=?
                          AND orders.side=? AND fills.market_event_id=?
                        """,
                        (account_id, row["symbol"], side.value, event_id),
                    ).fetchall()
                    consumed = sum(
                        (_decimal(item["quantity"]) for item in consumed_rows), ZERO
                    )
                    available = max(ZERO, available - consumed)
                depth[key] = available
            position_row = db.execute(
                "SELECT * FROM positions WHERE account_id=? AND symbol=?",
                (account_id, row["symbol"]),
            ).fetchone()
            current_qty = _decimal(position_row["quantity"] if position_row else None)
            remaining = _decimal(row["quantity"]) - _decimal(row["filled_quantity"])
            result = match_order(
                side=side,
                order_type=OrderType(row["order_type"]),
                remaining=remaining,
                limit_price=(
                    None if row["limit_price"] is None else _decimal(row["limit_price"])
                ),
                quote=quote,
                available_depth=depth[key],
                cash=_decimal(account["cash"]),
                fee_rate=_decimal(account["fee_rate"]),
                current_position=current_qty,
                allow_short=bool(account["allow_short"]),
            )
            filled_before = _decimal(row["filled_quantity"])
            if result.quantity > ZERO and result.price is not None:
                fee = fee_for(
                    result.quantity, result.price, _decimal(account["fee_rate"])
                )
                signed_cash = result.quantity * result.price
                cash = _decimal(account["cash"])
                cash = (
                    cash - signed_cash - fee
                    if side == Side.BUY
                    else cash + signed_cash - fee
                )
                fees_paid = _decimal(account["fees_paid"]) + fee
                position_result = apply_position_fill(
                    current_quantity=current_qty,
                    average_cost=_decimal(
                        position_row["average_cost"] if position_row else None
                    ),
                    side=side,
                    fill_quantity=result.quantity,
                    fill_price=result.price,
                )
                realized = _decimal(
                    position_row["realized_pnl"] if position_row else None
                ) + position_result.realized_delta
                db.execute(
                    """
                    INSERT INTO positions(
                        account_id, symbol, quantity, average_cost, realized_pnl, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, symbol) DO UPDATE SET
                        quantity=excluded.quantity, average_cost=excluded.average_cost,
                        realized_pnl=excluded.realized_pnl, updated_at=excluded.updated_at
                    """,
                    (
                        account_id,
                        row["symbol"],
                        str(position_result.quantity),
                        str(position_result.average_cost),
                        str(realized),
                        timestamp,
                    ),
                )
                db.execute(
                    """
                    INSERT OR IGNORE INTO fills(
                        id, order_id, market_event_id, quantity, price, fee, filled_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        row["id"],
                        event_id,
                        str(result.quantity),
                        str(result.price),
                        str(fee),
                        timestamp,
                    ),
                )
                account = dict(account)
                account["cash"] = str(cash)
                account["fees_paid"] = str(fees_paid)
                db.execute(
                    """
                    UPDATE accounts
                    SET cash=?, fees_paid=?, last_market_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (str(cash), str(fees_paid), timestamp, timestamp, account_id),
                )
                if depth[key] is not None:
                    depth[key] = max(ZERO, depth[key] - result.quantity)

            filled = filled_before + result.quantity
            if filled >= _decimal(row["quantity"]):
                status = OrderStatus.FILLED
            elif result.terminal:
                status = (
                    OrderStatus.REJECTED
                    if filled == ZERO and result.rejection
                    else OrderStatus.CANCELLED
                )
            elif filled > ZERO:
                status = OrderStatus.PARTIALLY_FILLED
            else:
                status = OrderStatus.OPEN
            db.execute(
                """
                UPDATE orders
                SET filled_quantity=?, status=?, rejection_code=?, updated_at=?
                WHERE id=?
                """,
                (str(filled), status.value, result.rejection, timestamp, row["id"]),
            )

    def _record_equity(
        self, db: Any, account_id: str, event_id: str, timestamp: str
    ) -> None:
        portfolio = self._portfolio_from_db(db, account_id)
        db.execute(
            """
            INSERT INTO equity_points(
                account_id, event_id, recorded_at, cash, equity,
                realized_pnl, unrealized_pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, event_id) DO UPDATE SET
                cash=excluded.cash, equity=excluded.equity,
                realized_pnl=excluded.realized_pnl,
                unrealized_pnl=excluded.unrealized_pnl
            """,
            (
                account_id,
                event_id,
                timestamp,
                str(portfolio["cash"]),
                str(portfolio["equity"]),
                str(portfolio["realized"]),
                str(portfolio["unrealized"]),
            ),
        )

    def _portfolio_from_db(self, db: Any, account_id: str) -> dict[str, Decimal]:
        account = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        rows = db.execute(
            """
            SELECT positions.*, quotes.bid, quotes.ask, quotes.last
            FROM positions LEFT JOIN quotes ON quotes.symbol=positions.symbol
            WHERE positions.account_id=?
            """,
            (account_id,),
        ).fetchall()
        realized = ZERO
        unrealized = ZERO
        value = ZERO
        for row in rows:
            qty = _decimal(row["quantity"])
            avg = _decimal(row["average_cost"])
            mark = self._mark_from_row(row)
            realized += _decimal(row["realized_pnl"])
            if mark is not None:
                unrealized += (mark - avg) * qty
                value += mark * qty
        cash = _decimal(account["cash"])
        return {
            "cash": cash,
            "equity": cash + value,
            "realized": realized,
            "unrealized": unrealized,
        }

    @staticmethod
    def _mark_from_row(row: Any) -> Decimal | None:
        bid = None if row["bid"] is None else _decimal(row["bid"])
        ask = None if row["ask"] is None else _decimal(row["ask"])
        if bid is not None and ask is not None and bid > ZERO and ask > ZERO:
            return (bid + ask) / Decimal(2)
        return None if row["last"] is None else _decimal(row["last"])

    @staticmethod
    def _quote_from_row(row: Any) -> Quote | None:
        if row is None:
            return None
        return Quote(
            symbol=row["symbol"],
            bid=None if row["bid"] is None else _decimal(row["bid"]),
            ask=None if row["ask"] is None else _decimal(row["ask"]),
            last=None if row["last"] is None else _decimal(row["last"]),
            bid_size=None if row["bid_size"] is None else _decimal(row["bid_size"]),
            ask_size=None if row["ask_size"] is None else _decimal(row["ask_size"]),
        )

    @staticmethod
    def _order_from_row(row: Any) -> Order:
        return Order(
            id=row["id"],
            account_id=row["account_id"],
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            side=Side(row["side"]),
            order_type=OrderType(row["order_type"]),
            quantity=_decimal(row["quantity"]),
            filled_quantity=_decimal(row["filled_quantity"]),
            limit_price=(
                None if row["limit_price"] is None else _decimal(row["limit_price"])
            ),
            status=OrderStatus(row["status"]),
            submitted_at=row["submitted_at"],
            updated_at=row["updated_at"],
        )
