"""PostgreSQL adapter. The ledger service and its transaction boundaries are shared.

The hosted demo serializes writes with a transaction-scoped advisory lock, just
as SQLite serializes writers locally. This trades write throughput for a small,
easy-to-audit concurrency model, across all serverless instances.
"""

import re
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


class Record(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return Record(row) if row is not None else None

    def fetchall(self):
        return [Record(row) for row in self.cursor.fetchall()]


class Connection:
    def __init__(self, connection):
        self.raw = connection

    def execute(self, sql, params=None):
        # All SQL is application-owned; only values go through placeholders.
        return Cursor(self.raw.execute(sql.replace("?", "%s"), params))

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


class PostgresDatabase:
    def __init__(self, url, schema="ledger"):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("Invalid database schema.")
        self.url = url
        self.schema = schema

    def initialize(self):
        # Migrations are applied explicitly by the owner, never per invocation.
        with self.connection() as conn:
            conn.execute("SELECT id FROM accounts LIMIT 0")

    @contextmanager
    def connection(self):
        tls = {}
        if conninfo_to_dict(self.url).get("host", "").endswith(".supabase.com"):
            tls = {
                "sslmode": "verify-full",
                "sslrootcert": str(Path(__file__).parent / "certs" / "supabase-ca.crt"),
            }
        with psycopg.connect(
            self.url,
            autocommit=True,
            row_factory=dict_row,
            prepare_threshold=None,
            connect_timeout=10,
            **tls,
        ) as raw:
            raw.execute(f"SET search_path TO {self.schema}, pg_catalog")
            raw.execute("SET statement_timeout = '15s'")
            yield Connection(raw)

    @contextmanager
    def transaction(self, *, write=True):
        with self.connection() as conn:
            conn.execute("BEGIN" if write else "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                conn.execute("SET LOCAL lock_timeout = '5s'")
                if write:
                    conn.execute("SELECT pg_advisory_xact_lock(842601928)")
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
