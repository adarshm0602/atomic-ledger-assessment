from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from tests.conftest import balance, count_rows, post_transaction, post_transfer
from tests.test_api import assert_error


def inject_failure(app, sql):
    with app.state.db.connection() as conn:
        conn.execute(sql)


@pytest.mark.parametrize("operation", ["BEFORE UPDATE ON accounts", "AFTER INSERT ON transactions"])
def test_transaction_rolls_back_on_database_failure(client, app, accounts, operation):
    post_transaction(client, accounts[0])
    inject_failure(
        app,
        f"CREATE TRIGGER fail_operation {operation} BEGIN SELECT RAISE(ABORT, 'injected failure'); END",
    )
    assert_error(
        post_transaction(client, accounts[0], "20", "debit", "failing"), 500, "internal_error"
    )
    assert balance(client, accounts[0]) == "100.00"
    assert count_rows(app, "transactions") == 1


@pytest.mark.parametrize(
    "target", ["destination_balance", "transfer_record", "debit_entry", "credit_entry"]
)
def test_transfer_rolls_back_every_intermediate_failure(client, app, accounts, target):
    a, b = accounts
    post_transaction(client, a, "100")
    post_transaction(client, b, "50")
    trigger = {
        "destination_balance": f"AFTER UPDATE ON accounts WHEN NEW.id = {b}",
        "transfer_record": "AFTER INSERT ON transfers",
        "debit_entry": "AFTER INSERT ON transactions WHEN NEW.transfer_id IS NOT NULL AND NEW.type = 'debit'",
        "credit_entry": "AFTER INSERT ON transactions WHEN NEW.transfer_id IS NOT NULL AND NEW.type = 'credit'",
    }[target]
    inject_failure(
        app,
        f"CREATE TRIGGER fail_transfer {trigger} BEGIN SELECT RAISE(ABORT, 'injected failure'); END",
    )
    assert_error(post_transfer(client, accounts), 500, "internal_error")
    assert (balance(client, a), balance(client, b)) == ("100.00", "50.00")
    assert count_rows(app, "transactions") == 2
    assert count_rows(app, "transfers") == 0
    # A rolled-back reference must be available for a later successful retry.
    with app.state.db.connection() as conn:
        conn.execute("DROP TRIGGER fail_transfer")
    assert post_transfer(client, accounts).status_code == 201


def test_destination_capacity_rolls_back_source_debit(client, app, accounts):
    post_transaction(client, accounts[0], "100")
    post_transaction(client, accounts[1], "999999999999.99")
    assert_error(post_transfer(client, accounts, "1"), 409, "balance_limit_exceeded")
    assert balance(client, accounts[0]) == "100.00"
    assert count_rows(app, "transactions") == 2
    assert count_rows(app, "transfers") == 0


def test_concurrent_debits_cannot_overdraw(client, app, accounts):
    post_transaction(client, accounts[0], "100")
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(
            pool.map(
                lambda i: post_transaction(client, accounts[0], "10", "debit", f"debit-{i}"),
                range(20),
            )
        )
    assert [response.status_code for response in responses].count(201) == 10
    assert [response.status_code for response in responses].count(409) == 10
    assert balance(client, accounts[0]) == "0.00"
    assert count_rows(app, "transactions") == 11


def test_concurrent_duplicate_requests_create_one_entry(client, app, accounts):
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(
            pool.map(
                lambda _: post_transaction(client, accounts[0], "1", reference="same"), range(12)
            )
        )
    assert [response.status_code for response in responses].count(201) == 1
    assert [response.status_code for response in responses].count(409) == 11
    assert balance(client, accounts[0]) == "1.00"
    assert count_rows(app, "transactions") == 1


def test_opposing_transfers_preserve_total_money(client, app, accounts):
    for account in accounts:
        post_transaction(client, account, "100")
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(
            pool.map(
                lambda i: post_transfer(
                    client,
                    accounts if i % 2 == 0 else list(reversed(accounts)),
                    "1",
                    f"transfer-{i}",
                ),
                range(40),
            )
        )
    assert all(response.status_code == 201 for response in responses)
    assert [balance(client, account) for account in accounts] == ["100.00", "100.00"]
    assert count_rows(app, "transactions") == 82
    assert count_rows(app, "transfers") == 40


def test_concurrent_duplicate_transfers(client, app, accounts):
    post_transaction(client, accounts[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: post_transfer(client, accounts), range(8)))
    assert [response.status_code for response in responses].count(201) == 1
    assert [response.status_code for response in responses].count(409) == 7
    assert [balance(client, account) for account in accounts] == ["70.00", "30.00"]
    assert count_rows(app, "transfers") == 1


def test_busy_database_returns_retryable_error(client, app, accounts):
    app.state.db.timeout = 0.02
    with app.state.db.transaction():
        response = post_transaction(client, accounts[0])
    assert_error(response, 503, "database_busy")
    assert response.headers["Retry-After"] == "1"
    assert count_rows(app, "transactions") == 0
    assert balance(client, accounts[0]) == "0.00"


def test_commit_failure_also_rolls_back(client, app, accounts, monkeypatch):
    post_transaction(client, accounts[0])
    # Defer an intentionally broken foreign key until COMMIT. This exercises a
    # real SQLite commit failure after all service-level statements succeeded.
    inject_failure(
        app,
        """
        CREATE TRIGGER fail_commit AFTER INSERT ON transactions
        BEGIN
            INSERT INTO transfers(source_account_id, destination_account_id,
                amount_cents, reference_id, created_at)
            VALUES(NEW.account_id, 999999, 100, NEW.reference_id, NEW.created_at);
        END
    """,
    )
    original_connection = app.state.db.connection

    @contextmanager
    def deferred_connection():
        with original_connection() as conn:
            conn.execute("PRAGMA defer_foreign_keys = ON")
            yield conn

    monkeypatch.setattr(app.state.db, "connection", deferred_connection)
    response = post_transaction(client, accounts[0], "1", "debit", "commit-failure")
    assert_error(response, 500, "internal_error")
    assert balance(client, accounts[0]) == "100.00"
    assert count_rows(app, "transactions") == 1
    assert count_rows(app, "transfers") == 0
