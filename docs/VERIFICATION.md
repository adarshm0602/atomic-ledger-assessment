# Verification record

## Full application update — 28 October 2026

- Local suite: **124 passed**, with four PostgreSQL-only tests skipped without a test URL.
- Real Supabase PostgreSQL suite: **4 passed** in the isolated `ledger_test` schema, including concurrent debits, duplicate submissions, seeded summary/search, and forced failure after the second transfer ledger entry.
- Ruff lint/format checks and JavaScript syntax validation passed.
- Browser checks confirmed account creation, a 100.25 credit, duplicate-reference rejection, overdraft rejection, and a 10.25 transfer updating both account cards.
- The new database is a dedicated Supabase Free project; Vercel hosting uses a verified Hobby-plan team. The server connects with a restricted database role, certificate and hostname verification, and a private schema with RLS. Supabase security advisors returned no findings.
- The responsive UI is served by the same FastAPI application; deployment uses persistent PostgreSQL, while local development retains SQLite.
- GitHub Actions: **128 passed**, with both SQLite and the PostgreSQL 17 service enabled. Ruff checks passed.
- Public deployment: <https://atomic-ledger-assessment.vercel.app>. Anonymous HTTP checks verified health, API documentation, a real 0.01 transfer, duplicate and overdraft rejection, and a reverse transfer restoring exact account balances. Four corresponding ledger entries persisted in hosted PostgreSQL.
- The live dashboard loaded from the hosted API without browser console warnings/errors. A 390px mobile layout and the desktop layout were visually checked. Filtered activity search and CSV download were verified in the browser.

## Original API baseline

Verified on 28 October 2026 with Python 3.12.12, using the dependencies in `uv.lock`.

| Check | Result |
| --- | --- |
| Fresh `uv sync --frozen` installation | Passed |
| `uv run pytest` | 110 passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed |
| Live Uvicorn startup with a new database file | Passed |
| `scripts/demo.py` over real HTTP | Passed: 100/50 → 70/80 |
| Duplicate transfer through real HTTP | 409; balances unchanged |
| Overdraft through real HTTP | 409; balances unchanged |
| Live `/docs` and `/redoc` | Both returned 200 |
| Live `/openapi.json` versus exported schema | Exact match |

Rollback tests inject real SQLite trigger failures after intermediate writes. A separate deferred foreign-key test forces failure at COMMIT. All assert unchanged balances and absence of partial ledger/transfer records. Concurrency tests use independent database connections with simultaneous HTTP requests.

The test run emits one upstream Starlette warning that its httpx-based test client is deprecated. The pinned client remains functional; all assertions pass. No warnings are suppressed.

The live demo used a scratch database outside the submission. The submission includes no prepopulated account data or database files. No cloud deployment or external services were used.
