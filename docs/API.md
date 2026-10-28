# API documentation

Base URL: `http://127.0.0.1:8000`. All POST bodies require `Content-Type: application/json` (application JSON subtype media types ending in `+json` are also accepted). Authentication is not required for this local assessment.

Amounts are returned as fixed two-decimal strings. Requests accept decimal strings or JSON numbers. Use strings in clients that may round decimal numbers. IDs in JSON bodies must be integers. Timestamps are UTC ISO 8601 strings.

## Create account

`POST /accounts` → **201**

```json
{"name": "Savings"}
```

Example response:

```json
{
  "id": 1,
  "name": "Savings",
  "balance": "0.00",
  "created_at": "2026-10-28T12:00:00.000000Z"
}
```

`name` is required, trimmed, and must have 1–100 characters. Unknown fields, including opening balances, return 422.

## Read account

`GET /accounts/{account_id}` → **200**, using the same account response shape.

A valid nonexistent ID returns 404. An invalid or out-of-range ID returns 422.

## List accounts

`GET /accounts?page=1&page_size=20` → **200**

```json
{
  "data": [
    {"id": 1, "name": "Savings", "balance": "0.00", "created_at": "2026-10-28T12:00:00.000000Z"}
  ],
  "pagination": {"page": 1, "page_size": 20, "total": 1, "total_pages": 1}
}
```

Lists are ordered by descending ID. `page` defaults to 1 and is between 1 and 1,000,000,000. `page_size` defaults to 20 and is between 1 and 100. Values must be positive decimal integers without leading zeroes. Invalid or unknown query parameters return 422. A page beyond the available records returns `data: []` with the actual total. Empty lists have `total_pages: 0`.

## Create transaction

`POST /transactions` → **201**

```json
{
  "account_id": 1,
  "type": "credit",
  "amount": "100.00",
  "reference_id": "opening-001"
}
```

Example response:

```json
{
  "id": 1,
  "account_id": 1,
  "type": "credit",
  "amount": "100.00",
  "balance_after": "100.00",
  "reference_id": "opening-001",
  "transfer_id": null,
  "created_at": "2026-10-28T12:00:01.000000Z"
}
```

All four request fields are required. `type` must be exactly `credit` or `debit`. Amount must be finite, greater than zero, exactly representable in cents, and no greater than 999999999999.99. `reference_id` is trimmed and must have 1–128 characters. The account must exist. Debits require sufficient balance; credits cannot exceed the balance ceiling.

The balance change and new ledger row are atomic. Responses represent the balance immediately after this transaction; subsequent transactions may change the current balance.

Duplicate references for the same account return **409**, including identical retries or a reference previously used by a transfer leg. Other accounts may use that reference independently. Rejected writes persist nothing.

## List account transactions

`GET /accounts/{account_id}/transactions?page=1&page_size=20` → **200**

Returns the same pagination envelope as `/accounts`, with transaction objects in `data`. Records are scoped to the account and ordered by descending transaction ID. Transfer entries are included with a non-null `transfer_id`. A nonexistent account returns 404 even if its history would be empty.

## Transfer money

`POST /transfers` → **201**

```json
{
  "source_account_id": 1,
  "destination_account_id": 2,
  "amount": "30.00",
  "reference_id": "transfer-001"
}
```

Example response, assuming starting balances of 100 and 50:

```json
{
  "id": 1,
  "source_account_id": 1,
  "destination_account_id": 2,
  "amount": "30.00",
  "reference_id": "transfer-001",
  "created_at": "2026-10-28T12:00:02.000000Z",
  "debit_transaction": {
    "id": 3,
    "account_id": 1,
    "type": "debit",
    "amount": "30.00",
    "balance_after": "70.00",
    "reference_id": "transfer-001",
    "transfer_id": 1,
    "created_at": "2026-10-28T12:00:02.000000Z"
  },
  "credit_transaction": {
    "id": 4,
    "account_id": 2,
    "type": "credit",
    "amount": "30.00",
    "balance_after": "80.00",
    "reference_id": "transfer-001",
    "transfer_id": 1,
    "created_at": "2026-10-28T12:00:02.000000Z"
  }
}
```

Both accounts must exist and differ. Source balance must cover the amount and destination balance must remain within the limit. Amount/reference validation matches standalone transactions. The reference must be unused on **both** accounts. Both balance updates, the transfer row, and both ledger rows commit together. Any failure rolls all of them back.

## Error contract

Every error has this shape:

```json
{
  "error": {
    "code": "insufficient_balance",
    "message": "Account has insufficient balance.",
    "details": []
  }
}
```

Validation errors include field details:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {"field": "body.amount", "message": "Input should be greater than 0", "type": "greater_than"}
    ]
  }
}
```

| Status | Code | Meaning |
| --- | --- | --- |
| 400 | `invalid_json` | Malformed JSON, duplicate keys, or nonstandard numeric constants |
| 400 | `invalid_request` | Body could not be parsed, e.g. invalid text encoding |
| 404 | `account_not_found` | A requested account does not exist |
| 404 | `not_found` | Unknown route |
| 405 | `method_not_allowed` | Unsupported method; `Allow` header is retained |
| 409 | `duplicate_transaction` | Reference already exists on an affected account |
| 409 | `insufficient_balance` | Debit would make the source balance negative |
| 409 | `balance_limit_exceeded` | Credit would exceed 999999999999.99 |
| 415 | `unsupported_media_type` | POST body is not sent with a supported JSON content type |
| 422 | `validation_error` | Missing/invalid fields, unknown fields, wrong body shape, invalid ID/pagination, or self-transfer |
| 500 | `internal_error` | Unexpected failure; failed operation is rolled back and internals are logged server-side |
| 503 | `database_busy` | Database lock wait expired; `Retry-After: 1` is included |

After a 503 or an uncertain network response, retry with the **same** reference. A 409 on retry means the reference is already used; query the relevant account's history and compare its recorded transaction before deciding what to do next. Reusing a new reference for an uncertain request could duplicate the intended business action.

## curl example

On a fresh database, create the two accounts and fund them:

```sh
curl -i -X POST http://127.0.0.1:8000/accounts -H 'Content-Type: application/json' -d '{"name":"Account A"}'
curl -i -X POST http://127.0.0.1:8000/accounts -H 'Content-Type: application/json' -d '{"name":"Account B"}'
curl -i -X POST http://127.0.0.1:8000/transactions -H 'Content-Type: application/json' -d '{"account_id":1,"type":"credit","amount":"100.00","reference_id":"fund-a"}'
curl -i -X POST http://127.0.0.1:8000/transactions -H 'Content-Type: application/json' -d '{"account_id":2,"type":"credit","amount":"50.00","reference_id":"fund-b"}'
curl -i -X POST http://127.0.0.1:8000/transfers -H 'Content-Type: application/json' -d '{"source_account_id":1,"destination_account_id":2,"amount":"30.00","reference_id":"transfer-001"}'
curl http://127.0.0.1:8000/accounts/1
curl http://127.0.0.1:8000/accounts/2
```

Use the actual returned IDs when the database already contains accounts, or use `scripts/demo.py` to handle IDs automatically.
