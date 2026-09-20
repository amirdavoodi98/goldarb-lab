"""Versioned SQLite storage for offline simulation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Self

SCHEMA_VERSION = 1

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
    submitted_at TEXT NOT NULL,
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
    UNIQUE(order_id, market_event_id)
);
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


class SQLiteRepository:
    """Small transactional repository; one writer, concurrent WAL readers."""

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
        elif int(row["version"]) != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported simulation schema {row['version']}; expected {SCHEMA_VERSION}"
            )

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
