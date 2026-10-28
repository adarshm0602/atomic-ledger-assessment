# Atomic Ledger

A runnable account API for the supplied Full Stack Developer Assessment. It creates accounts, records credits and debits, lists transaction history, and implements the bonus money transfer API. Every money movement and its ledger entries commit together or roll back together.

## Run locally

Requirements: Python 3.12+ with SQLite 3.37+ (for strict tables). No database server, credentials, or cloud account is required.

Get the source:

```sh
git clone https://github.com/adarshm0602/atomic-ledger-assessment.git
cd atomic-ledger-assessment
```

From this directory, using [uv](https://docs.astral.sh/uv/):

```sh
uv sync --frozen
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Alternatively, using Python and pip:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On Windows, activate with `.venv\Scripts\activate` instead. For only the runtime dependencies, install `requirements.txt`.

Open:

- Interactive API documentation: <http://127.0.0.1:8000/docs>
- Alternative API reference: <http://127.0.0.1:8000/redoc>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>
- Health check: <http://127.0.0.1:8000/health>

The database is created automatically at `data/ledger.sqlite3` and persists across restarts. Set `DATABASE_PATH` in your shell to use a different file:

```sh
DATABASE_PATH=data/demo.sqlite3 uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`.env.example` documents the setting; the application does not automatically load `.env`. Use a fresh path for a fresh database.

## Try the assessment example

With the server running, open a second terminal in this directory:

```sh
uv run python scripts/demo.py
```

The script creates two new accounts on every run, credits them with 100 and 50, transfers 30, and checks that the resulting balances are **70.00** and **80.00**. It also checks duplicate-reference rejection and insufficient-balance rejection. It deliberately persists this sample data. An optional first argument selects another API base URL.

## Endpoints

| Method | Path | Result |
| --- | --- | --- |
| POST | `/accounts` | Create an account at zero balance |
| GET | `/accounts` | Paginated accounts |
| GET | `/accounts/{account_id}` | Account and current balance |
| POST | `/transactions` | Atomic credit or debit |
| GET | `/accounts/{account_id}/transactions` | Paginated account ledger |
| POST | `/transfers` | Atomic transfer with debit and credit ledger entries |
| GET | `/health` | Database connectivity check |

See [API documentation](docs/API.md) for payloads, response examples, pagination, and the error contract. A portable [OpenAPI document](docs/openapi.json) is also included.

## Integrity and atomicity

`app/db.py` owns transaction boundaries. Each write opens its own database connection and executes `BEGIN IMMEDIATE` before reading balances or checking references. The service performs every write for the operation on that same connection. A successful exit commits; any exception, including a commit failure, rolls back. No endpoint changes a balance directly outside this boundary.

For a standalone transaction, the balance update and transaction insert share one commit. For a transfer, the source debit, destination credit, transfer record, and both ledger entries share one commit. No committed partial transfer is exposed through this API.

Balance checks happen while holding the database writer lock, so two requests cannot both spend the same funds based on an old balance. Conditional updates also enforce balance bounds. This works across independent connections and processes sharing the same local SQLite file. SQLite serializes writers; it is appropriate for this local assessment, with throughput limited by that choice.

Money is stored as integer cents. JSON decimal numbers are parsed directly into `Decimal`, and responses use fixed two-decimal strings. Neither storage nor balance arithmetic uses binary floating point.

Database constraints enforce foreign keys, nonnegative bounded integer balances, positive integer amounts, valid transaction types, required names and references, distinct transfer accounts, and unique `(account_id, reference_id)` transaction references. The API additionally validates input types, lengths, extra fields, pagination, and available funds. References are checked for both transfer legs.

Reads of paginated data and their counts use one database snapshot. Lists have a deterministic descending ID order. Offset pagination can shift between separate requests if other clients insert records.

SQLite uses WAL mode, a five-second lock wait, and `synchronous=FULL`. If lock acquisition times out, the API returns `503 database_busy` with `Retry-After: 1`. Schema version 1 is initialized idempotently at startup; this project does not yet provide upgrade migrations for future schema changes. The database file should live on local storage.

Implementation references: [SQLite transactions](https://www.sqlite.org/lang_transaction.html), [SQLite isolation](https://www.sqlite.org/isolation.html), [FastAPI error handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/).

## Verification

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

With pip, run `python -m pytest`, `ruff check .`, and `ruff format --check .` in the activated environment.

Tests use isolated temporary database files. Coverage includes:

- Input validation, malformed JSON, missing accounts, pagination, decimal precision, balance limits, and consistent HTTP errors.
- Successful credits/debits and the required 100/50 → 70/80 transfer example.
- Database constraints and persistence after restarting the application.
- Forced database failures after balance updates, transfer insertion, and either transfer ledger entry, with rollback assertions.
- Concurrent debit, duplicate transaction, duplicate transfer, and opposing-transfer requests against real database connections.
- Retryable database-lock errors.

## Project structure

```text
app/
  main.py          HTTP routes, JSON decoding, application lifecycle, errors
  schemas.py       Input validation and output contracts
  service.py       Account and money-movement operations
  db.py            Schema, connections, transaction boundaries
  errors.py        Shared error contract
tests/             API, database, rollback and concurrency tests
docs/API.md        Written API reference
docs/ASSUMPTIONS.md Scope and design decisions
docs/openapi.json  Exported API schema
scripts/demo.py    Live HTTP demo using Python's standard library
pyproject.toml     Runtime and development dependencies
uv.lock            Locked dependency resolution
requirements*.txt Pip-compatible dependency exports
```

## Scope and assumptions

The supplied excerpt starts with atomicity and sections 7–11; earlier assessment sections were not provided. The account and history endpoints above fill in the minimum workflow needed to exercise those requirements. The excerpt specifies API behavior, so this submission provides interactive API documentation as its user interface. It includes no separate frontend, authentication, external payment processing, or deployment.

See [Assumptions](docs/ASSUMPTIONS.md) for currency, reference reuse, retry behavior, limits, and scope details.
