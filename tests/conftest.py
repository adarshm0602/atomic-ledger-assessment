import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(str(tmp_path / "ledger.sqlite3"))


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def accounts(client):
    return [client.post("/accounts", json={"name": name}).json()["id"] for name in ("A", "B")]


def post_transaction(client, account_id, amount="100.00", kind="credit", reference="funding"):
    return client.post(
        "/transactions",
        json={"account_id": account_id, "type": kind, "amount": amount, "reference_id": reference},
    )


def post_transfer(client, accounts, amount="30.00", reference="transfer-1"):
    return client.post(
        "/transfers",
        json={
            "source_account_id": accounts[0],
            "destination_account_id": accounts[1],
            "amount": amount,
            "reference_id": reference,
        },
    )


def balance(client, account_id):
    return client.get(f"/accounts/{account_id}").json()["balance"]


def count_rows(app, table):
    assert table in {"accounts", "transactions", "transfers"}
    with app.state.db.connection() as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
