"""Exercise a running API using only Python's standard library."""

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    base_url = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")

    def request(path, payload=None, expected=200):
        body = json.dumps(payload).encode() if payload is not None else None
        req = Request(base_url + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as response:
                status, raw = response.status, response.read()
        except HTTPError as exc:
            status, raw = exc.code, exc.read()
        result = json.loads(raw)
        if status != expected:
            raise RuntimeError(f"{path}: expected {expected}, received {status}: {result}")
        return result

    request("/health")
    accounts = [
        request("/accounts", {"name": name}, 201)["id"]
        for name in ("Demo Account A", "Demo Account B")
    ]
    for account_id, amount in zip(accounts, ("100.00", "50.00"), strict=True):
        request(
            "/transactions",
            {
                "account_id": account_id,
                "type": "credit",
                "amount": amount,
                "reference_id": "demo-funding",
            },
            201,
        )
    payload = {
        "source_account_id": accounts[0],
        "destination_account_id": accounts[1],
        "amount": "30.00",
        "reference_id": "demo-transfer",
    }
    transfer = request("/transfers", payload, 201)
    balances = [request(f"/accounts/{account_id}")["balance"] for account_id in accounts]
    if balances != ["70.00", "80.00"]:
        raise RuntimeError(f"Unexpected balances: {balances}")
    duplicate = request("/transfers", payload, 409)
    rejected = request(
        "/transactions",
        {
            "account_id": accounts[0],
            "type": "debit",
            "amount": "1000.00",
            "reference_id": "demo-overdraft",
        },
        409,
    )
    final_balances = [request(f"/accounts/{account_id}")["balance"] for account_id in accounts]
    if final_balances != balances:
        raise RuntimeError("Rejected requests changed balances.")
    print(
        json.dumps(
            {
                "accounts": accounts,
                "transfer_id": transfer["id"],
                "balances": final_balances,
                "duplicate_error": duplicate["error"]["code"],
                "overdraft_error": rejected["error"]["code"],
                "result": "PASS",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (URLError, RuntimeError) as exc:
        sys.exit(f"Demo failed: {exc}")
