import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import balance, post_transaction, post_transfer


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["details"], list)


def test_create_read_and_persist(client, app):
    response = client.post("/accounts", json={"name": "  Savings  "})
    assert response.status_code == 201
    account = response.json()
    assert account["name"] == "Savings"
    assert account["balance"] == "0.00"
    assert account["created_at"].endswith("Z")
    with TestClient(create_app(app.state.db.path)) as second:
        assert second.get(f"/accounts/{account['id']}").json() == account


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": " \t "},
        {"name": None},
        {"name": 123},
        {"name": "a" * 101},
        {"name": "A", "balance": 100},
        [],
        "A",
    ],
)
def test_invalid_account_data(client, payload):
    assert_error(client.post("/accounts", json=payload), 422, "validation_error")


def test_credit_debit_decimal_accuracy(client, accounts):
    account_id = accounts[0]
    for i in range(10):
        assert post_transaction(client, account_id, "0.10", reference=f"c-{i}").status_code == 201
    debit = post_transaction(client, account_id, "0.30", "debit", "debit")
    assert debit.status_code == 201
    assert debit.json()["balance_after"] == "0.70"
    assert debit.json()["transfer_id"] is None
    assert balance(client, account_id) == "0.70"
    assert post_transaction(client, account_id, "0.70", "debit", "empty").status_code == 201
    assert balance(client, account_id) == "0.00"


def test_json_decimal_numbers_are_not_rounded(client, accounts):
    response = client.post(
        "/transactions",
        content=f'{{"account_id":{accounts[0]},"type":"credit","amount":0.10,"reference_id":"decimal"}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201
    assert response.json()["amount"] == "0.10"
    response = client.post(
        "/transactions",
        content=f'{{"account_id":{accounts[0]},"type":"credit","amount":1.00000000000000001,"reference_id":"precision"}}',
        headers={"Content-Type": "application/json"},
    )
    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize(
    "amount",
    [
        0,
        -1,
        "0",
        "-0.01",
        "1.001",
        "1000000000000.00",
        "NaN",
        "Infinity",
        "abc",
        "",
        True,
        None,
        [],
        {},
    ],
)
def test_invalid_amounts(client, accounts, amount):
    assert_error(post_transaction(client, accounts[0], amount), 422, "validation_error")
    assert balance(client, accounts[0]) == "0.00"


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "refund"),
        ("type", "Credit"),
        ("type", None),
        ("reference_id", ""),
        ("reference_id", "  "),
        ("reference_id", 1),
        ("reference_id", "r" * 129),
        ("account_id", 0),
        ("account_id", -1),
        ("account_id", "1"),
        ("account_id", True),
        ("account_id", 1.5),
        ("account_id", 9223372036854775808),
    ],
)
def test_invalid_transaction_fields(client, accounts, field, value):
    payload = {
        "account_id": accounts[0],
        "type": "credit",
        "amount": "10.00",
        "reference_id": "ref",
    }
    payload[field] = value
    assert_error(client.post("/transactions", json=payload), 422, "validation_error")


@pytest.mark.parametrize("missing", ["account_id", "type", "amount", "reference_id"])
def test_missing_transaction_fields(client, accounts, missing):
    payload = {
        "account_id": accounts[0],
        "type": "credit",
        "amount": "10.00",
        "reference_id": "ref",
    }
    del payload[missing]
    assert_error(client.post("/transactions", json=payload), 422, "validation_error")


def test_unknown_transaction_fields(client, accounts):
    assert_error(
        client.post(
            "/transactions",
            json={
                "account_id": accounts[0],
                "type": "credit",
                "amount": "10",
                "reference_id": "r",
                "typo": 1,
            },
        ),
        422,
        "validation_error",
    )


def test_duplicate_reference_is_per_account(client, accounts):
    a, b = accounts
    assert post_transaction(client, a, reference="shared").status_code == 201
    assert_error(
        post_transaction(client, a, "1.00", "debit", "shared"), 409, "duplicate_transaction"
    )
    assert post_transaction(client, b, reference="shared").status_code == 201
    assert_error(post_transaction(client, a, reference=" shared "), 409, "duplicate_transaction")
    assert balance(client, a) == "100.00"


def test_insufficient_balance_and_missing_account(client, accounts):
    assert_error(
        post_transaction(client, accounts[0], "0.01", "debit"), 409, "insufficient_balance"
    )
    assert_error(post_transaction(client, 999), 404, "account_not_found")
    assert_error(client.get("/accounts/999"), 404, "account_not_found")
    assert_error(client.get("/accounts/999/transactions"), 404, "account_not_found")


@pytest.mark.parametrize(
    "account_id", ["abc", "0", "-1", "1.5", "1.0", "true", "9223372036854775808"]
)
def test_invalid_path_ids(client, account_id):
    assert_error(client.get(f"/accounts/{account_id}"), 422, "validation_error")


def test_pagination_and_account_filtering(client, accounts):
    for i in range(5):
        assert post_transaction(client, accounts[0], reference=str(i)).status_code == 201
    post_transaction(client, accounts[1], reference="other")
    response = client.get(f"/accounts/{accounts[0]}/transactions?page=2&page_size=2")
    assert response.status_code == 200
    body = response.json()
    assert [row["reference_id"] for row in body["data"]] == ["2", "1"]
    assert body["pagination"] == {"page": 2, "page_size": 2, "total": 5, "total_pages": 3}
    assert client.get(f"/accounts/{accounts[0]}/transactions?page=9").json()["data"] == []
    listing = client.get("/accounts?page_size=1").json()
    assert listing["data"][0]["id"] == accounts[1]
    assert listing["pagination"]["total"] == 2


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page=-1",
        "page=x",
        "page=1.0",
        "page=01",
        "page=1e2",
        "page=1000000001",
        "page_size=0",
        "page_size=-1",
        "page_size=101",
        "page_size=1.5",
        "page_size=",
        "unknown=1",
    ],
)
def test_invalid_pagination(client, accounts, query):
    for path in ("/accounts", f"/accounts/{accounts[0]}/transactions"):
        assert_error(client.get(f"{path}?{query}"), 422, "validation_error")


def test_empty_pagination(client):
    assert client.get("/accounts").json() == {
        "data": [],
        "pagination": {"page": 1, "page_size": 20, "total": 0, "total_pages": 0},
    }


@pytest.mark.parametrize(
    "body",
    [
        '{"name":',
        '{"name":"A","name":"B"}',
        '{"name":NaN}',
        '{"name":Infinity}',
        '{"name":-Infinity}',
        "",
    ],
)
def test_malformed_json(client, body):
    status = 422 if body == "" else 400
    code = "validation_error" if body == "" else "invalid_json"
    assert_error(
        client.post("/accounts", content=body, headers={"Content-Type": "application/json"}),
        status,
        code,
    )


def test_media_type_and_http_errors(client):
    assert_error(client.post("/accounts", content="name=A"), 415, "unsupported_media_type")
    assert_error(client.get("/unknown"), 404, "not_found")
    response = client.delete("/accounts")
    assert_error(response, 405, "method_not_allowed")
    assert "allow" in response.headers


def test_balance_capacity(client, accounts):
    assert post_transaction(client, accounts[0], "999999999999.99").status_code == 201
    assert_error(
        post_transaction(client, accounts[0], ".01", reference="overflow"),
        409,
        "balance_limit_exceeded",
    )
    assert balance(client, accounts[0]) == "999999999999.99"


def test_transfer_example(client, accounts):
    a, b = accounts
    post_transaction(client, a, "100")
    post_transaction(client, b, "50")
    response = post_transfer(client, accounts)
    assert response.status_code == 201
    transfer = response.json()
    assert transfer["amount"] == "30.00"
    assert transfer["debit_transaction"]["transfer_id"] == transfer["id"]
    assert transfer["credit_transaction"]["transfer_id"] == transfer["id"]
    assert transfer["debit_transaction"]["type"] == "debit"
    assert transfer["credit_transaction"]["type"] == "credit"
    assert (balance(client, a), balance(client, b)) == ("70.00", "80.00")
    assert_error(post_transfer(client, accounts), 409, "duplicate_transaction")
    assert (balance(client, a), balance(client, b)) == ("70.00", "80.00")


@pytest.mark.parametrize(
    "source,destination,amount,status,code",
    [
        (999, 1, "1", 404, "account_not_found"),
        (1, 999, "1", 404, "account_not_found"),
        (1, 2, "1", 409, "insufficient_balance"),
        (1, 1, "1", 422, "validation_error"),
        (1, 2, "0", 422, "validation_error"),
        (1, 2, "-1", 422, "validation_error"),
        (1, 2, "1.001", 422, "validation_error"),
    ],
)
def test_invalid_transfers(client, accounts, source, destination, amount, status, code):
    assert_error(post_transfer(client, (source, destination), amount), status, code)
    assert [balance(client, account) for account in accounts] == ["0.00", "0.00"]


def test_destination_reference_collision(client, accounts):
    post_transaction(client, accounts[0])
    post_transaction(client, accounts[1], "1", reference="taken")
    assert_error(post_transfer(client, accounts, reference="taken"), 409, "duplicate_transaction")
    assert [balance(client, account) for account in accounts] == ["100.00", "1.00"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_account_id", "1"),
        ("source_account_id", True),
        ("destination_account_id", -1),
        ("reference_id", ""),
        ("reference_id", None),
        ("amount", True),
    ],
)
def test_invalid_transfer_fields(client, accounts, field, value):
    payload = {
        "source_account_id": accounts[0],
        "destination_account_id": accounts[1],
        "amount": "1",
        "reference_id": "r",
    }
    payload[field] = value
    assert_error(client.post("/transfers", json=payload), 422, "validation_error")


@pytest.mark.parametrize(
    "field", ["source_account_id", "destination_account_id", "amount", "reference_id"]
)
def test_missing_transfer_fields(client, accounts, field):
    payload = {
        "source_account_id": accounts[0],
        "destination_account_id": accounts[1],
        "amount": "1",
        "reference_id": "r",
    }
    del payload[field]
    assert_error(client.post("/transfers", json=payload), 422, "validation_error")


def test_docs_and_openapi(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/transfers"]["post"]["responses"]["422"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("ErrorResponse")


def test_database_constraints(app, client, accounts):
    with app.state.db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE accounts SET balance_cents = -1 WHERE id = ?", (accounts[0],))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE accounts SET balance_cents = 1.5 WHERE id = ?", (accounts[0],))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO transactions(account_id,type,amount_cents,balance_after_cents,reference_id,created_at) VALUES(999,'credit',100,100,'r','now')"
            )
        for kind, amount, reference in [("bad", 1, "r"), ("credit", 0, "r"), ("credit", 1, "")]:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO transactions(account_id,type,amount_cents,balance_after_cents,reference_id,created_at) VALUES(?,?,?,?,?,'now')",
                    (accounts[0], kind, amount, 100, reference),
                )
    post_transaction(client, accounts[0])
    with app.state.db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO transactions(account_id,type,amount_cents,balance_after_cents,reference_id,created_at) VALUES(?,'credit',100,100,'funding','now')",
                (accounts[0],),
            )
