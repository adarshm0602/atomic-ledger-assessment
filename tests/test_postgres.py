"""Real PostgreSQL integration tests, enabled by TEST_DATABASE_URL.

Only the dedicated ledger_test schema is used. These tests never modify the
deployed ledger schema. CI supplies an isolated PostgreSQL service.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.postgres import PostgresDatabase
from tests.conftest import balance, post_transaction, post_transfer
from tests.test_api import assert_error

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL to run real PostgreSQL integration tests.",
)


@pytest.fixture
def pg_client():
    url = os.environ["TEST_DATABASE_URL"]
    db = PostgresDatabase(url, schema="ledger_test")
    # Our disposable schema is provisioned by CI or the project owner first.
    schema = (
        Path("db/postgres.sql")
        .read_text()
        .split("REVOKE ALL ON SCHEMA")[0]
        .replace("ledger.", "ledger_test.")
        .replace("CREATE SCHEMA IF NOT EXISTS ledger;", "")
    )
    with db.connection() as conn:
        if conn.execute("SELECT to_regnamespace('ledger_test')").fetchone()[0] is None:
            conn.execute("CREATE SCHEMA ledger_test")
        conn.raw.execute(schema)
        conn.execute("TRUNCATE transactions, transfers, accounts RESTART IDENTITY CASCADE")
    with patch.dict(
        os.environ, {"DATABASE_URL": url, "DATABASE_SCHEMA": "ledger_test", "DEMO_SEED": "false"}
    ):
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    with db.connection() as conn:
        conn.execute("TRUNCATE transactions, transfers, accounts RESTART IDENTITY CASCADE")


def new_accounts(client):
    return [client.post("/accounts", json={"name": name}).json()["id"] for name in ("A", "B")]


def test_postgres_transfer_summary_and_persistence(pg_client):
    accounts = new_accounts(pg_client)
    post_transaction(pg_client, accounts[0], "100")
    post_transaction(pg_client, accounts[1], "50")
    assert post_transfer(pg_client, accounts, "30").status_code == 201
    assert [balance(pg_client, a) for a in accounts] == ["70.00", "80.00"]
    summary = pg_client.get("/overview")
    assert summary.status_code == 200, summary.text
    assert summary.json()["total_balance"] == "150.00"
    assert summary.json()["credited"] == "180.00"
    assert pg_client.get("/activity?q=transfer").json()["pagination"]["total"] == 2
    assert_error(post_transfer(pg_client, accounts, "30"), 409, "duplicate_transaction")


def test_postgres_concurrent_debits_and_duplicates(pg_client):
    accounts = new_accounts(pg_client)
    post_transaction(pg_client, accounts[0], "100")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda i: post_transaction(pg_client, accounts[0], "10", "debit", f"debit-{i}"),
                range(20),
            )
        )
    assert [r.status_code for r in results].count(201) == 10
    assert [r.status_code for r in results].count(409) == 10
    assert balance(pg_client, accounts[0]) == "0.00"
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda _: post_transaction(pg_client, accounts[1], "1", reference="duplicate"),
                range(8),
            )
        )
    assert [r.status_code for r in results].count(201) == 1
    assert [r.status_code for r in results].count(409) == 7
    assert balance(pg_client, accounts[1]) == "1.00"


def test_postgres_rollback_after_second_ledger_entry(pg_client):
    accounts = new_accounts(pg_client)
    post_transaction(pg_client, accounts[0], "100")
    db = pg_client.app.state.db
    with db.connection() as conn:
        conn.execute(
            """CREATE FUNCTION fail_transfer_entry() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.type = 'credit' AND NEW.transfer_id IS NOT NULL THEN RAISE EXCEPTION 'injected failure'; END IF; RETURN NEW; END; $$"""
        )
        conn.execute(
            "CREATE TRIGGER fail_transfer AFTER INSERT ON transactions FOR EACH ROW EXECUTE FUNCTION fail_transfer_entry()"
        )
    try:
        assert_error(post_transfer(pg_client, accounts, "30"), 500, "internal_error")
        assert [balance(pg_client, a) for a in accounts] == ["100.00", "0.00"]
        assert pg_client.get("/activity").json()["pagination"]["total"] == 1
        with db.connection() as conn:
            assert conn.execute("SELECT count(*) FROM transfers").fetchone()[0] == 0
    finally:
        with db.connection() as conn:
            conn.execute("DROP TRIGGER fail_transfer ON transactions")
            conn.execute("DROP FUNCTION fail_transfer_entry()")
    assert post_transfer(pg_client, accounts, "30").status_code == 201


def test_postgres_seed_and_literal_search(pg_client):
    assert pg_client.post("/demo/seed", json={}).json() == {"seeded": True}
    assert pg_client.get("/overview").json()["total_balance"] == "35840.00"
    assert pg_client.post("/demo/seed", json={}).json() == {"seeded": False}
    assert pg_client.get("/activity?q=%25").json()["pagination"]["total"] == 0
