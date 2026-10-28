"""Connection-per-operation SQLite persistence with explicit transaction ownership."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

MAX_CENTS = 99_999_999_999_999
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 100),
    balance_cents INTEGER NOT NULL DEFAULT 0
        CHECK(balance_cents BETWEEN 0 AND {MAX_CENTS}),
    created_at TEXT NOT NULL
) STRICT;
CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_account_id INTEGER NOT NULL REFERENCES accounts(id),
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount_cents INTEGER NOT NULL CHECK(amount_cents BETWEEN 1 AND {MAX_CENTS}),
    reference_id TEXT NOT NULL CHECK(length(trim(reference_id)) BETWEEN 1 AND 128),
    created_at TEXT NOT NULL,
    CHECK(source_account_id != destination_account_id),
    UNIQUE(source_account_id, reference_id)
) STRICT;
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    type TEXT NOT NULL CHECK(type IN ('credit', 'debit')),
    amount_cents INTEGER NOT NULL CHECK(amount_cents BETWEEN 1 AND {MAX_CENTS}),
    balance_after_cents INTEGER NOT NULL CHECK(balance_after_cents BETWEEN 0 AND {MAX_CENTS}),
    reference_id TEXT NOT NULL CHECK(length(trim(reference_id)) BETWEEN 1 AND 128),
    transfer_id INTEGER REFERENCES transfers(id),
    created_at TEXT NOT NULL,
    UNIQUE(account_id, reference_id)
) STRICT;
CREATE INDEX IF NOT EXISTS transactions_account_id_id ON transactions(account_id, id DESC);
PRAGMA user_version = 1;
"""


class Database:
    def __init__(self, path: str, timeout: float = 5.0):
        if path == ":memory:":
            raise ValueError("Use a file database; operations use independent connections.")
        self.path = path
        self.timeout = timeout

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self, *, write: bool = True):
        with self.connection() as conn:
            # Obtain the writer lock BEFORE balance/duplicate checks. This also
            # serializes writers in other processes, unlike an application lock.
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
