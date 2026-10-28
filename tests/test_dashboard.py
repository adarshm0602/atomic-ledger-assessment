import pytest

from tests.conftest import balance, post_transaction, post_transfer
from tests.test_api import assert_error


def test_application_and_static_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Your money, in view." in page.text
    for file in ("app.js", "style.css", "favicon.svg"):
        assert client.get(f"/static/{file}").status_code == 200


def test_empty_overview(client):
    result = client.get("/overview").json()
    assert result["total_balance"] == "0.00"
    assert result["credited"] == result["debited"] == "0.00"
    assert result["account_count"] == result["transaction_count"] == 0
    assert len(result["daily"]) == 7


def test_summary_reconciles_transfer_legs(client, accounts):
    post_transaction(client, accounts[0], "100")
    post_transaction(client, accounts[1], "50")
    post_transfer(client, accounts, "30")
    result = client.get("/overview").json()
    assert result["total_balance"] == "150.00"
    assert result["account_count"] == 2
    assert result["transaction_count"] == 4
    assert result["credited"] == "180.00"
    assert result["debited"] == "30.00"
    assert result["daily"][-1]["credit"] == "180.00"
    assert result["daily"][-1]["debit"] == "30.00"


def test_activity_search_filters_and_pagination(client, accounts):
    post_transaction(client, accounts[0], "100", reference="invoice_10%")
    post_transaction(client, accounts[0], "5", "debit", "invoice_101")
    post_transaction(client, accounts[1], "50", reference="Other")
    body = client.get("/activity", params={"q": "INVOICE_10%"}).json()
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["account_name"] == "A"
    assert body["data"][0]["reference_id"] == "invoice_10%"
    body = client.get("/activity", params={"account_id": accounts[0], "type": "debit"}).json()
    assert body["pagination"]["total"] == 1
    assert body["data"][0]["amount"] == "5.00"
    body = client.get("/activity?page=2&page_size=1").json()
    assert body["data"][0]["reference_id"] == "invoice_101"
    assert body["pagination"]["total_pages"] == 3


@pytest.mark.parametrize(
    "query",
    [
        "account_id=0",
        "account_id=1.5",
        "type=refund",
        "page=0",
        "page_size=101",
        "unknown=x",
        "q=" + "x" * 129,
    ],
)
def test_activity_validation(client, query):
    assert_error(client.get("/activity?" + query), 422, "validation_error")


def test_activity_missing_account(client):
    assert_error(client.get("/activity?account_id=999"), 404, "account_not_found")


def test_seed_demo_is_idempotent_and_consistent(client):
    assert client.post("/demo/seed", json={}).json() == {"seeded": True}
    before = client.get("/overview").json()
    assert before["total_balance"] == "35840.00"
    assert before["account_count"] == 3
    assert before["transaction_count"] == 11
    assert client.post("/demo/seed", json={}).json() == {"seeded": False}
    assert client.get("/overview").json() == before


def test_seed_never_changes_an_existing_workspace(client, accounts):
    post_transaction(client, accounts[0], "12.34")
    assert client.post("/demo/seed", json={}).json() == {"seeded": False}
    assert balance(client, accounts[0]) == "12.34"
    assert client.get("/overview").json()["account_count"] == 2
