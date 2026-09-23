"""Local paper broker facade: OrderManager + MarketBook + Matching + Portfolio + Persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from ..execution import (
    FeeModel,
    LatencyModel,
    NoLatency,
    NoSlippage,
    PercentFee,
    SlippageModel,
)
from .engine import ZERO
from .market_book import MarketBook
from .matching import MatchingEngine, QuoteMatching
from .models import (
    WORKING_STATUSES,
    Account,
    Fill,
    MarketSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Quote,
    Side,
    TimeInForce,
    decimal_value,
)
from .order_manager import OrderManager
from .pipeline import ExecutionPipeline, active_after_latency
from .portfolio_service import LedgerPosition, LedgerState, PortfolioService
from .storage import (
    SQLitePersistence,
    account_from_row,
    fill_from_row,
    insert_order_event,
    order_from_row,
    upsert_order,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class LocalPaperBroker:
    """Strategy-stable paper broker; internals are delegated collaborators."""

    def __init__(
        self,
        path: str | Path,
        *,
        matching: MatchingEngine | None = None,
        fee: FeeModel | None = None,
        slippage: SlippageModel | None = None,
        latency: LatencyModel | None = None,
    ) -> None:
        self._repo = SQLitePersistence(path)
        self.orders = OrderManager()
        self.book = MarketBook()
        self.portfolio_service = PortfolioService()
        self.fee = fee or PercentFee("0.0005")
        self.slippage = slippage or NoSlippage()
        self.latency = latency or NoLatency()
        self.pipeline = ExecutionPipeline(
            matching or QuoteMatching(),
            slippage=self.slippage,
            fee=self.fee,
            portfolio=self.portfolio_service,
        )
        self._hydrate()
        latest = self._repo.connection.execute(
            "SELECT timestamp FROM market_events ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        self._last_timestamp = (
            None if latest is None else datetime.fromisoformat(latest["timestamp"])
        )

    def configure_execution(
        self,
        *,
        fee: FeeModel | None = None,
        slippage: SlippageModel | None = None,
        latency: LatencyModel | None = None,
    ) -> None:
        """Wire engine-level models onto the order-path pipeline (once)."""
        if fee is not None:
            self.fee = fee
        if slippage is not None:
            self.slippage = slippage
        if latency is not None:
            self.latency = latency
        self.pipeline = ExecutionPipeline(
            self.pipeline.matching,
            slippage=self.slippage,
            fee=self.fee,
            portfolio=self.portfolio_service,
        )

    def _hydrate(self) -> None:
        for row in self._repo.connection.execute("SELECT * FROM orders"):
            order = order_from_row(row)
            fills = [
                fill_from_row(item)
                for item in self._repo.connection.execute(
                    "SELECT * FROM fills WHERE order_id=? ORDER BY filled_at, id",
                    (order.id,),
                )
            ]
            self.orders.restore(order, fills)
        for row in self._repo.connection.execute("SELECT * FROM quotes"):
            quote = Quote(
                symbol=row["symbol"],
                bid=None if row["bid"] is None else decimal_value(row["bid"]),
                ask=None if row["ask"] is None else decimal_value(row["ask"]),
                last=None if row["last"] is None else decimal_value(row["last"]),
                bid_size=None if row["bid_size"] is None else decimal_value(row["bid_size"]),
                ask_size=None if row["ask_size"] is None else decimal_value(row["ask_size"]),
            )
            # Reconstruct book without monotonic check on hydrate.
            self.book._quotes[quote.symbol] = quote
            self.book._event_id = row["event_id"]
            self.book._timestamp = datetime.fromisoformat(row["timestamp"])

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
        fee_rate: Decimal | float | str | None = None,
        allow_short: bool = False,
        account_id: str | None = None,
    ) -> Account:
        cash = decimal_value(initial_cash)
        fee = self.fee.rate() if fee_rate is None else decimal_value(fee_rate)
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
        return account_from_row(row)

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
        time_in_force: TimeInForce | str = TimeInForce.DAY,
    ) -> Order:
        self.get_account(account_id)
        if client_order_id:
            existing = self.orders.get_by_client(account_id, client_order_id)
            if existing is not None:
                return existing
        clock = self.book.timestamp or datetime.now(UTC)
        submitted_at = clock
        active_at = active_after_latency(submitted_at, self.latency)
        stamp = submitted_at.isoformat()
        order = self.orders.create(
            account_id=account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
            time_in_force=time_in_force,
            submitted_at=stamp,
            active_at=active_at.isoformat(),
        )

        with self._repo.transaction() as db:
            upsert_order(db, order)
            for event in self.orders.events_for(order.id):
                insert_order_event(db, event)
            if clock >= active_at:
                order = self.orders.accept(order.id, at=stamp)
                upsert_order(db, order)
                for event in self.orders.events_for(order.id)[-1:]:
                    insert_order_event(db, event)
                if self.book.event_id is not None and self.book.timestamp is not None:
                    self._match_account(
                        db,
                        account_id,
                        self.book.event_id,
                        self.book.timestamp,
                        only_order_id=order.id,
                    )
                    self._record_equity(
                        db, account_id, self.book.event_id, self.book.timestamp.isoformat()
                    )
        return self.get_order(account_id, order.id)

    def cancel_order(
        self,
        account_id: str,
        order_id: str,
        *,
        confirm: bool = True,
    ) -> Order:
        order = self.get_order(account_id, order_id)
        stamp = (self.book.timestamp or datetime.now(UTC)).isoformat()
        with self._repo.transaction() as db:
            pending = self.orders.request_cancel(order.id, at=stamp)
            upsert_order(db, pending)
            for event in self.orders.events_for(order.id)[-1:]:
                insert_order_event(db, event)
            if confirm and pending.status == OrderStatus.CANCEL_PENDING:
                cancelled = self.orders.confirm_cancel(order.id, at=stamp)
                upsert_order(db, cancelled)
                for event in self.orders.events_for(order.id)[-1:]:
                    insert_order_event(db, event)
        return self.get_order(account_id, order_id)

    def feed(self, snapshot: MarketSnapshot) -> bool:
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
            if self._last_timestamp is not None and self._last_timestamp > timestamp:
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
            self.book.update(snapshot)
            self._activate_due_orders(db, timestamp)
            accounts = db.execute(
                "SELECT id FROM accounts WHERE status='ACTIVE' ORDER BY created_at, id"
            ).fetchall()
            for account in accounts:
                self._match_account(db, account["id"], snapshot.event_id, timestamp)
                self._record_equity(db, account["id"], snapshot.event_id, stamp)
        self._last_timestamp = timestamp
        return True

    def settle_delayed_orders(self) -> None:
        """Activate SubmitLatency-deferred orders against the last book (end of run)."""
        if self.book.event_id is None or self.book.timestamp is None:
            return
        created = [
            order
            for order in self.orders._orders.values()
            if order.status == OrderStatus.CREATED
        ]
        if not created:
            return
        latest_active = max(
            datetime.fromisoformat(order.active_at or order.submitted_at) for order in created
        )
        clock = max(self.book.timestamp, latest_active)
        with self._repo.transaction() as db:
            self._activate_due_orders(db, clock)
            accounts = db.execute(
                "SELECT id FROM accounts WHERE status='ACTIVE' ORDER BY created_at, id"
            ).fetchall()
            event_id = f"settle:{self.book.event_id}:{clock.isoformat()}"
            if db.execute(
                "SELECT 1 FROM market_events WHERE event_id=?", (event_id,)
            ).fetchone():
                event_id = f"{event_id}:{uuid.uuid4()}"
            db.execute(
                "INSERT INTO market_events(event_id, timestamp) VALUES (?, ?)",
                (event_id, clock.isoformat()),
            )
            for account in accounts:
                self._match_account(db, account["id"], event_id, clock)
                self._record_equity(db, account["id"], event_id, clock.isoformat())

    def _activate_due_orders(self, db: Any, clock: datetime) -> None:
        for order in list(self.orders._orders.values()):
            if order.status != OrderStatus.CREATED:
                continue
            active_at = datetime.fromisoformat(order.active_at or order.submitted_at)
            if clock >= active_at:
                accepted = self.orders.accept(order.id, at=clock.isoformat())
                upsert_order(db, accepted)
                for event in self.orders.events_for(order.id)[-1:]:
                    insert_order_event(db, event)

    def _match_account(
        self,
        db: Any,
        account_id: str,
        event_id: str,
        timestamp: datetime,
        *,
        only_order_id: str | None = None,
    ) -> None:
        account_row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        account = account_from_row(account_row)
        positions = self._load_positions(db, account_id)
        ledger = LedgerState(
            cash=account.cash,
            fees_paid=account.fees_paid,
            positions=positions,
        )
        depth: dict[tuple[str, str], Decimal | None] = {}
        candidates = [
            order
            for order in self.orders.list_for_account(account_id)
            if order.status in WORKING_STATUSES
            and (only_order_id is None or order.id == only_order_id)
        ]
        for order in candidates:
            quote = self.book.quote(order.symbol)
            key = (order.symbol, order.side.value)
            if key not in depth:
                available = (
                    quote.ask_size
                    if quote and order.side == Side.BUY
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
                        (account_id, order.symbol, order.side.value, event_id),
                    ).fetchall()
                    consumed = sum(
                        (decimal_value(item["quantity"]) for item in consumed_rows), ZERO
                    )
                    available = max(ZERO, available - consumed)
                depth[key] = available

            result = self.pipeline.run(
                order,
                quote=quote,
                available_depth=depth[key],
                ledger=ledger,
                allow_short=account.allow_short,
                market_event_id=event_id,
                market_timestamp=timestamp,
                fee_rate=account.fee_rate,
            )
            if result.fills:
                pipe = result.fills[0]
                # Atomic commit: fill + order + account + position + events
                db.execute(
                    """
                    INSERT OR IGNORE INTO fills(
                        id, order_id, market_event_id, quantity, price, fee, filled_at,
                        raw_match_price, market_timestamp, execution_timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pipe.fill.id,
                        pipe.fill.order_id,
                        pipe.fill.market_event_id,
                        str(pipe.fill.quantity),
                        str(pipe.fill.price),
                        str(pipe.fill.fee),
                        pipe.fill.filled_at,
                        _text(pipe.fill.raw_match_price),
                        pipe.fill.market_timestamp,
                        pipe.fill.execution_timestamp,
                    ),
                )
                if db.execute(
                    "SELECT changes()"
                ).fetchone()[0] == 0:
                    # duplicate fill for (order, event)
                    continue
                updated = self.orders.apply_fill(order.id, pipe.fill)
                if (
                    updated.status == OrderStatus.CANCEL_PENDING
                    and updated.remaining_quantity > ZERO
                ):
                    # One late fill allowed on this market event; then cancel remainder.
                    updated = self.orders.confirm_cancel(
                        order.id, at=timestamp.isoformat()
                    )
                upsert_order(db, updated)
                for event in self.orders.events_for(order.id)[-2:]:
                    insert_order_event(db, event)
                pos = pipe.ledger.position
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
                        pos.symbol,
                        str(pos.quantity),
                        str(pos.average_cost),
                        str(pos.realized_pnl),
                        timestamp.isoformat(),
                    ),
                )
                db.execute(
                    """
                    UPDATE accounts
                    SET cash=?, fees_paid=?, last_market_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        str(pipe.ledger.cash),
                        str(pipe.ledger.fees_paid),
                        timestamp.isoformat(),
                        timestamp.isoformat(),
                        account_id,
                    ),
                )
                ledger = LedgerState(
                    cash=pipe.ledger.cash,
                    fees_paid=pipe.ledger.fees_paid,
                    positions={**ledger.positions, pos.symbol: pos},
                )
                if depth[key] is not None:
                    depth[key] = max(ZERO, depth[key] - pipe.fill.quantity)  # type: ignore[operator]
                order = updated

            match = result.match
            if match.proposed is None and match.terminal:
                if order.order_type == OrderType.MARKET or order.filled_quantity == ZERO:
                    closed = self.orders.close_unfilled(
                        order.id,
                        at=timestamp.isoformat(),
                        rejection=match.rejection,
                    )
                    upsert_order(db, closed)
                    for event in self.orders.events_for(order.id)[-1:]:
                        insert_order_event(db, event)
            elif (
                order.status == OrderStatus.CANCEL_PENDING
                and match.proposed is None
            ):
                cancelled = self.orders.confirm_cancel(order.id, at=timestamp.isoformat())
                upsert_order(db, cancelled)
                for event in self.orders.events_for(order.id)[-1:]:
                    insert_order_event(db, event)

    def _load_positions(self, db: Any, account_id: str) -> dict[str, LedgerPosition]:
        rows = db.execute(
            "SELECT * FROM positions WHERE account_id=?", (account_id,)
        ).fetchall()
        return {
            row["symbol"]: LedgerPosition(
                symbol=row["symbol"],
                quantity=decimal_value(row["quantity"]),
                average_cost=decimal_value(row["average_cost"]),
                realized_pnl=decimal_value(row["realized_pnl"]),
            )
            for row in rows
        }

    def get_order(self, account_id: str, order_id: str) -> Order:
        row = self._repo.connection.execute(
            "SELECT * FROM orders WHERE id=? AND account_id=?", (order_id, account_id)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown order: {order_id}")
        return order_from_row(row)

    def list_orders(self, account_id: str) -> list[Order]:
        rows = self._repo.connection.execute(
            "SELECT * FROM orders WHERE account_id=? ORDER BY submitted_at, id",
            (account_id,),
        ).fetchall()
        return [order_from_row(row) for row in rows]

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
        return [fill_from_row(row) for row in rows]

    def portfolio(self, account_id: str) -> Portfolio:
        account = self.get_account(account_id)
        positions = self._load_positions(self._repo.connection, account_id)
        marks = {symbol: self.book.quote(symbol) for symbol in positions}
        as_of = self._repo.connection.execute(
            "SELECT last_market_at FROM accounts WHERE id=?", (account_id,)
        ).fetchone()["last_market_at"]
        return self.portfolio_service.snapshot(account, positions, marks, as_of=as_of)

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

    def _record_equity(
        self, db: Any, account_id: str, event_id: str, timestamp: str
    ) -> None:
        account = account_from_row(
            db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        )
        positions = self._load_positions(db, account_id)
        marks = {
            symbol: Quote(
                symbol=symbol,
                bid=None if row["bid"] is None else decimal_value(row["bid"]),
                ask=None if row["ask"] is None else decimal_value(row["ask"]),
                last=None if row["last"] is None else decimal_value(row["last"]),
            )
            if (
                row := db.execute("SELECT * FROM quotes WHERE symbol=?", (symbol,)).fetchone()
            )
            is not None
            else None
            for symbol in positions
        }
        portfolio = self.portfolio_service.snapshot(
            account, positions, marks, as_of=timestamp
        )
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
                str(portfolio.cash),
                str(portfolio.equity),
                str(portfolio.realized_pnl),
                str(portfolio.unrealized_pnl),
            ),
        )


# Public alias — keep Strategy / engine imports stable.
LocalSimulator = LocalPaperBroker
