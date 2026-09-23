"""Versioned SQLite persistence for local paper trading."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

from .models import (
    Account,
    Fill,
    Order,
    OrderEvent,
    OrderEventType,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
    decimal_value,
)

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    initial_cash TEXT NOT NULL,
    cash TEXT NOT NULL,
    fee_rate TEXT NOT NULL,
    allow_short INTEGER NOT NULL,
    fees_paid TEXT NOT NULL,
    last_market_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity TEXT NOT NULL,
    filled_quantity TEXT NOT NULL,
    limit_price TEXT,
    status TEXT NOT NULL,
    rejection_code TEXT,
    time_in_force TEXT NOT NULL DEFAULT 'DAY',
    avg_fill_price TEXT,
    submitted_at TEXT NOT NULL,
    created_at TEXT,
    accepted_at TEXT,
    closed_at TEXT,
    active_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, client_order_id)
);
CREATE INDEX IF NOT EXISTS sim_orders_open_idx
    ON orders(account_id, status, submitted_at);
CREATE TABLE IF NOT EXISTS fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    market_event_id TEXT NOT NULL,
    quantity TEXT NOT NULL,
    price TEXT NOT NULL,
    fee TEXT NOT NULL,
    filled_at TEXT NOT NULL,
    raw_match_price TEXT,
    market_timestamp TEXT,
    execution_timestamp TEXT,
    UNIQUE(order_id, market_event_id)
);
CREATE TABLE IF NOT EXISTS order_events (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS sim_order_events_order_idx
    ON order_events(order_id, timestamp, id);
CREATE TABLE IF NOT EXISTS positions (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    quantity TEXT NOT NULL,
    average_cost TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(account_id, symbol)
);
CREATE TABLE IF NOT EXISTS quotes (
    symbol TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    bid TEXT,
    ask TEXT,
    last TEXT,
    bid_size TEXT,
    ask_size TEXT
);
CREATE TABLE IF NOT EXISTS market_events (
    event_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sim_market_events_timestamp_idx
    ON market_events(timestamp DESC);
CREATE TABLE IF NOT EXISTS equity_points (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    cash TEXT NOT NULL,
    equity TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    unrealized_pnl TEXT NOT NULL,
    PRIMARY KEY(account_id, event_id)
);
CREATE INDEX IF NOT EXISTS sim_equity_points_history_idx
    ON equity_points(account_id, recorded_at, event_id);
"""


class SQLitePersistence:
    """Transactional store; fill + order + account + events must share one txn."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(_SCHEMA)
        row = self.connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,)
            )
            return
        version = int(row["version"])
        if version == SCHEMA_VERSION:
            return
        if version == 1:
            self._migrate_v1_to_v2()
            return
        raise RuntimeError(
            f"Unsupported simulation schema {version}; expected {SCHEMA_VERSION}"
        )

    def _migrate_v1_to_v2(self) -> None:
        cols = {row[1] for row in self.connection.execute("PRAGMA table_info(orders)")}
        alters = []
        if "time_in_force" not in cols:
            alters.append("ALTER TABLE orders ADD COLUMN time_in_force TEXT NOT NULL DEFAULT 'DAY'")
        if "avg_fill_price" not in cols:
            alters.append("ALTER TABLE orders ADD COLUMN avg_fill_price TEXT")
        if "created_at" not in cols:
            alters.append("ALTER TABLE orders ADD COLUMN created_at TEXT")
        if "accepted_at" not in cols:
            alters.append("ALTER TABLE orders ADD COLUMN accepted_at TEXT")
        if "closed_at" not in cols:
            alters.append("ALTER TABLE orders ADD COLUMN closed_at TEXT")
        if "active_at" not in cols:
            alters.append("ALTER TABLE orders ADD COLUMN active_at TEXT")
        for statement in alters:
            self.connection.execute(statement)
        self.connection.execute(
            "UPDATE orders SET status='ACCEPTED' WHERE status='OPEN'"
        )
        fill_cols = {row[1] for row in self.connection.execute("PRAGMA table_info(fills)")}
        if "raw_match_price" not in fill_cols:
            self.connection.execute("ALTER TABLE fills ADD COLUMN raw_match_price TEXT")
        if "market_timestamp" not in fill_cols:
            self.connection.execute("ALTER TABLE fills ADD COLUMN market_timestamp TEXT")
        if "execution_timestamp" not in fill_cols:
            self.connection.execute("ALTER TABLE fills ADD COLUMN execution_timestamp TEXT")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS order_events (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS sim_order_events_order_idx
                ON order_events(order_id, timestamp, id);
            """
        )
        self.connection.execute("UPDATE schema_meta SET version=?", (SCHEMA_VERSION,))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# Backward-compatible name used by older imports/tests.
SQLiteRepository = SQLitePersistence


def account_from_row(row: Any) -> Account:
    return Account(
        id=row["id"],
        label=row["label"],
        status=row["status"],
        initial_cash=decimal_value(row["initial_cash"]),
        cash=decimal_value(row["cash"]),
        fee_rate=decimal_value(row["fee_rate"]),
        allow_short=bool(row["allow_short"]),
        fees_paid=decimal_value(row["fees_paid"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def order_from_row(row: Any) -> Order:
    status_raw = row["status"]
    status = OrderStatus.ACCEPTED if status_raw == "OPEN" else OrderStatus(status_raw)
    return Order(
        id=row["id"],
        account_id=row["account_id"],
        client_order_id=row["client_order_id"],
        symbol=row["symbol"],
        side=Side(row["side"]),
        order_type=OrderType(row["order_type"]),
        quantity=decimal_value(row["quantity"]),
        filled_quantity=decimal_value(row["filled_quantity"]),
        limit_price=(
            None if row["limit_price"] is None else decimal_value(row["limit_price"])
        ),
        status=status,
        submitted_at=row["submitted_at"],
        updated_at=row["updated_at"],
        time_in_force=TimeInForce(row["time_in_force"] or "DAY"),
        rejection_code=row["rejection_code"],
        avg_fill_price=(
            None
            if row["avg_fill_price"] is None
            else decimal_value(row["avg_fill_price"])
        ),
        created_at=row["created_at"] or row["submitted_at"],
        accepted_at=row["accepted_at"],
        closed_at=row["closed_at"],
        active_at=row["active_at"] or row["submitted_at"],
    )


def fill_from_row(row: Any) -> Fill:
    return Fill(
        id=row["id"],
        order_id=row["order_id"],
        market_event_id=row["market_event_id"],
        quantity=decimal_value(row["quantity"]),
        price=decimal_value(row["price"]),
        fee=decimal_value(row["fee"]),
        filled_at=row["filled_at"],
        raw_match_price=(
            None
            if row["raw_match_price"] is None
            else decimal_value(row["raw_match_price"])
        ),
        market_timestamp=row["market_timestamp"],
        execution_timestamp=row["execution_timestamp"],
    )


def insert_order_event(db: sqlite3.Connection, event: OrderEvent) -> None:
    import json

    db.execute(
        """
        INSERT OR IGNORE INTO order_events(id, order_id, event_type, timestamp, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event.id,
            event.order_id,
            event.event_type.value,
            event.timestamp,
            json.dumps(event.payload),
        ),
    )


def upsert_order(db: sqlite3.Connection, order: Order) -> None:
    db.execute(
        """
        INSERT INTO orders(
            id, account_id, client_order_id, symbol, side, order_type,
            quantity, filled_quantity, limit_price, status, rejection_code,
            time_in_force, avg_fill_price, submitted_at, created_at, accepted_at,
            closed_at, active_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            filled_quantity=excluded.filled_quantity,
            status=excluded.status,
            rejection_code=excluded.rejection_code,
            avg_fill_price=excluded.avg_fill_price,
            accepted_at=excluded.accepted_at,
            closed_at=excluded.closed_at,
            active_at=excluded.active_at,
            updated_at=excluded.updated_at
        """,
        (
            order.id,
            order.account_id,
            order.client_order_id,
            order.symbol,
            order.side.value,
            order.order_type.value,
            str(order.quantity),
            str(order.filled_quantity),
            None if order.limit_price is None else str(order.limit_price),
            order.status.value,
            order.rejection_code,
            order.time_in_force.value,
            None if order.avg_fill_price is None else str(order.avg_fill_price),
            order.submitted_at,
            order.created_at,
            order.accepted_at,
            order.closed_at,
            order.active_at,
            order.updated_at,
        ),
    )
