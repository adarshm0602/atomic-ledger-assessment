# Verification record

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
