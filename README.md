# Atomic Ledger

**Live application:** [atomic-ledger-assessment.vercel.app](https://atomic-ledger-assessment.vercel.app) · [Live API docs](https://atomic-ledger-assessment.vercel.app/docs)

A full-stack account ledger for the supplied Full Stack Developer Assessment. The responsive dashboard manages accounts, records credits and debits, searches transaction history, exports CSV, and transfers money. Every money movement and its ledger entries commit together or roll back together. FastAPI serves both the UI and API; SQLite supports local use and PostgreSQL supports durable hosted data.

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

- Application dashboard: <http://127.0.0.1:8000/>
- Interactive API documentation: <http://127.0.0.1:8000/docs>
- Alternative API reference: <http://127.0.0.1:8000/redoc>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>
- Health check: <http://127.0.0.1:8000/health>

The database is created automatically at `data/ledger.sqlite3` and persists across restarts. Set `DATABASE_PATH` in your shell to use a different file:

```sh
DATABASE_PATH=data/demo.sqlite3 uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`.env.example` documents the setting; the application does not automatically load `.env`. Use a fresh path for a fresh database.

## Explore the dashboard

The dashboard includes Overview, Accounts, and Activity views; a seven-day movement chart; account creation; credit/debit forms; atomic transfers; account/type filters; reference search; transaction details; pagination; and filtered CSV exports. Dialogs support keyboard navigation and display API validation errors without discarding form values. The layout adapts to desktop and mobile screens. There is no frontend build step or external JavaScript runtime dependency in the browser.

For sample accounts and transactions, click **Load sample data** in an empty workspace, or start with `DEMO_SEED=true`. Sample data is inserted once, atomically, and never overwrites an existing workspace. The displayed currency is USD. The hosted application is a shared assessment sandbox with demo funds; it does not move actual money.

## Free-tier deployment

The hosted setup uses **Vercel Hobby** for the FastAPI application and UI, and a dedicated **Supabase Free** PostgreSQL project in Mumbai. No paid compute, add-ons, or subscriptions are provisioned. Database records live in PostgreSQL and survive Vercel restarts/redeployments. Hosting remains subject to each provider's free usage limits; Supabase Free projects may pause after inactivity and require resuming in its dashboard. See [Vercel Hobby](https://vercel.com/docs/plans/hobby) and [Supabase pricing](https://supabase.com/pricing).

To reproduce the deployment:

1. Create a free Supabase project and apply [db/postgres.sql](db/postgres.sql) using the project owner's SQL editor. The `ledger` schema is private and has RLS enabled.
2. Provision a dedicated `ledger_server` login role with a generated password using your secret manager or SQL client. Apply [db/server-grants.sql](db/server-grants.sql). Keep the password out of Git and browser code.
3. Copy the **Session pooler** connection hostname from the project's Connect dialog. Use port 5432 and the username `ledger_server.<project-ref>`. The exact hostname cannot be inferred from the region.
4. Import this GitHub repository into a Vercel Hobby project with the FastAPI preset. [vercel.json](vercel.json) and `tool.vercel.entrypoint` configure the entrypoint and Mumbai region.
5. Add `DATABASE_URL` as a **sensitive production environment variable**, containing the server role's pooler URL. Optionally set `DEMO_SEED=true` for sample data. Then deploy.

The server validates the Supabase TLS certificate using the bundled public CA certificate in `app/certs/`. No private key is included. The certificate came from the download link in Supabase Database Settings and expires in April 2031; update it from the provider when rotated. Vercel deployments require `DATABASE_URL` and deliberately refuse to use ephemeral SQLite. Database initialization checks schema availability; it never applies PostgreSQL DDL during an HTTP request or function startup.

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
| GET | `/overview` | Workspace totals and seven-day chart data |
| GET | `/activity` | Searchable, filtered, paginated activity across accounts |
| POST | `/demo/seed` | Seed sample data only when the workspace is empty |

See [API documentation](docs/API.md) for payloads, response examples, pagination, and the error contract. A portable [OpenAPI document](docs/openapi.json) is also included.

## Integrity and atomicity

`app/db.py` owns transaction boundaries. Each write opens its own database connection and executes `BEGIN IMMEDIATE` before reading balances or checking references. The service performs every write for the operation on that same connection. A successful exit commits; any exception, including a commit failure, rolls back. No endpoint changes a balance directly outside this boundary.

For a standalone transaction, the balance update and transaction insert share one commit. For a transfer, the source debit, destination credit, transfer record, and both ledger entries share one commit. No committed partial transfer is exposed through this API.

Balance checks happen while holding the database writer lock, so two requests cannot both spend the same funds based on an old balance. Conditional updates also enforce balance bounds. This works across independent connections and processes sharing the same local SQLite file. SQLite serializes writers; it is appropriate for this local assessment, with throughput limited by that choice.

Money is stored as integer cents. JSON decimal numbers are parsed directly into `Decimal`, and responses use fixed two-decimal strings. Neither storage nor balance arithmetic uses binary floating point.

Database constraints enforce foreign keys, nonnegative bounded integer balances, positive integer amounts, valid transaction types, required names and references, distinct transfer accounts, and unique `(account_id, reference_id)` transaction references. The API additionally validates input types, lengths, extra fields, pagination, and available funds. References are checked for both transfer legs.

Reads of paginated data and their counts use one database snapshot. Lists have a deterministic descending ID order. Offset pagination can shift between separate requests if other clients insert records.

SQLite uses WAL mode, a five-second lock wait, and `synchronous=FULL`. If lock acquisition times out, the API returns `503 database_busy` with `Retry-After: 1`. Schema version 1 is initialized idempotently at startup; this project does not yet provide upgrade migrations for future schema changes. The database file should live on local storage.

For PostgreSQL, the same service operations run inside explicit transactions. A transaction-scoped advisory lock serializes money writes across serverless instances, with a five-second lock timeout. This deliberately favors a straightforward correctness model for the assessment over maximum write throughput. Read transactions use repeatable-read snapshots. A server-only role has access to the private ledger schema; Supabase's anonymous and authenticated browser roles have none. Money still uses integer cents, with the same constraints and reference semantics. All financial writes must go through this service to participate in its advisory lock; conditional balance updates and unique constraints remain additional safeguards.

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
- Dashboard data reconciliation, safe demo seeding, literal search, filters and static assets.

Four additional PostgreSQL integration tests run automatically in GitHub Actions against an isolated PostgreSQL 17 service, using only `ledger_test`. To run them locally, provide `TEST_DATABASE_URL` for a disposable test database or a preprovisioned `ledger_test` schema. They verify the same transfer, summary, duplicate, concurrency, rollback, and seed/search behavior against real PostgreSQL. They never modify the production `ledger` schema.

## Project structure

```text
app/
  main.py          HTTP routes, JSON decoding, application lifecycle, errors
  schemas.py       Input validation and output contracts
  service.py       Account and money-movement operations
  db.py            Schema, connections, transaction boundaries
  postgres.py      PostgreSQL connection and transaction adapter
  static/          Responsive dashboard (HTML, CSS, JavaScript, favicon)
  certs/           Public Supabase TLS CA certificate
  errors.py        Shared error contract
tests/             API, database, rollback and concurrency tests
docs/API.md        Written API reference
docs/ASSUMPTIONS.md Scope and design decisions
docs/openapi.json  Exported API schema
scripts/demo.py    Live HTTP demo using Python's standard library
db/               PostgreSQL bootstrap schema and server-role grants
vercel.json       Hosting configuration
pyproject.toml     Runtime and development dependencies
uv.lock            Locked dependency resolution
requirements*.txt Pip-compatible dependency exports
```

## Scope and assumptions

The supplied excerpt starts with atomicity and sections 7–11; earlier assessment sections were not provided. The account and history endpoints fill in the minimum workflow needed to exercise those requirements. The application includes a complete dashboard and deployment configuration. Authentication and external payment processing are outside the assessment scope; the public deployment is a shared demo workspace.

See [Assumptions](docs/ASSUMPTIONS.md) for currency, reference reuse, retry behavior, limits, and scope details.
