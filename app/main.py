import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated

from fastapi import FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BeforeValidator
from starlette.exceptions import HTTPException

from app.db import Database
from app.errors import APIError, ErrorResponse, error_body
from app.schemas import (
    Account,
    AccountCreate,
    Page,
    PaginationQuery,
    Transaction,
    TransactionCreate,
    Transfer,
    TransferCreate,
    positive_integer,
)
from app.service import Ledger

logger = logging.getLogger("atomic_ledger")


class DecimalRequest(Request):
    async def json(self):
        if not hasattr(self, "_json"):
            body = await self.body()

            def invalid_constant(value):
                raise json.JSONDecodeError(
                    f"Invalid JSON number: {value}", body.decode(errors="replace"), 0
                )

            def unique_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise json.JSONDecodeError(
                            f"Duplicate JSON key: {key}", body.decode(errors="replace"), 0
                        )
                    result[key] = value
                return result

            # Preserve decimal JSON numbers without a binary float round trip.
            self._json = json.loads(
                body,
                parse_float=Decimal,
                parse_constant=invalid_constant,
                object_pairs_hook=unique_keys,
            )
        return self._json


class JSONRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            if request.method == "POST":
                media_type = (
                    request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if not (
                    media_type == "application/json"
                    or (media_type.startswith("application/") and media_type.endswith("+json"))
                ):
                    raise APIError(
                        415, "unsupported_media_type", "Send the request body as application/json."
                    )
            return await original(DecimalRequest(request.scope, request.receive))

        return handler


PathAccountId = Annotated[
    int,
    BeforeValidator(positive_integer),
    Path(gt=0, le=9_223_372_036_854_775_807),
]


def create_app(database_path: str | None = None) -> FastAPI:
    db = Database(database_path or os.getenv("DATABASE_PATH", "data/ledger.sqlite3"))
    ledger = Ledger(db)

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        yield

    app = FastAPI(
        title="Atomic Ledger API",
        version="1.0.0",
        description="Accounts, credit/debit transactions and atomic money transfers. Amounts are returned as decimal strings. New accounts start at zero.",
        lifespan=lifespan,
        responses={
            status: {"model": ErrorResponse, "description": description}
            for status, description in {
                400: "Malformed JSON",
                404: "Account or route not found",
                409: "Duplicate reference, insufficient balance, or balance limit",
                415: "Unsupported media type",
                422: "Validation error",
                500: "Internal error",
                503: "Database busy; retry later",
            }.items()
        },
    )
    app.router.route_class = JSONRoute
    app.state.db = db

    @app.exception_handler(APIError)
    async def api_error(request, exc):
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = exc.errors()
        malformed = any(error["type"] == "json_invalid" for error in errors)
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in errors
        ]
        return JSONResponse(
            error_body(
                "invalid_json" if malformed else "validation_error",
                "Request body contains invalid JSON."
                if malformed
                else "Request validation failed.",
                details,
            ),
            status_code=400 if malformed else 422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = {404: "not_found", 405: "method_not_allowed", 400: "invalid_request"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            error_body(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
            return JSONResponse(
                error_body(
                    "duplicate_transaction", "Reference already exists for an affected account."
                ),
                status_code=409,
            )
        logger.error("Database integrity failure", exc_info=exc)
        return JSONResponse(
            error_body("internal_error", "The operation could not be completed."), status_code=500
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def operational_error(request, exc):
        if exc.sqlite_errorcode & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return JSONResponse(
                error_body(
                    "database_busy",
                    "Database is busy. Retry the request using the same reference_id.",
                ),
                status_code=503,
                headers={"Retry-After": "1"},
            )
        logger.error("Database operation failed", exc_info=exc)
        return JSONResponse(
            error_body("internal_error", "The operation could not be completed."), status_code=500
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error("Unhandled request failure", exc_info=exc)
        return JSONResponse(
            error_body("internal_error", "The operation could not be completed."), status_code=500
        )

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["Health"])
    def health():
        with db.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.post("/accounts", response_model=Account, status_code=201, tags=["Accounts"])
    def create_account(data: AccountCreate):
        """Create an account with a zero balance."""
        return ledger.create_account(data.name)

    @app.get("/accounts", response_model=Page[Account], tags=["Accounts"])
    def list_accounts(pagination: Annotated[PaginationQuery, Query()]):
        return ledger.list_accounts(pagination.page, pagination.page_size)

    @app.get("/accounts/{account_id}", response_model=Account, tags=["Accounts"])
    def get_account(account_id: PathAccountId):
        return ledger.get_account(account_id)

    @app.post("/transactions", response_model=Transaction, status_code=201, tags=["Transactions"])
    def create_transaction(data: TransactionCreate):
        """Atomically update a balance and persist a transaction. Duplicate references return 409."""
        return ledger.create_transaction(data)

    @app.get(
        "/accounts/{account_id}/transactions",
        response_model=Page[Transaction],
        tags=["Transactions"],
    )
    def list_transactions(
        account_id: PathAccountId, pagination: Annotated[PaginationQuery, Query()]
    ):
        return ledger.list_transactions(account_id, pagination.page, pagination.page_size)

    @app.post("/transfers", response_model=Transfer, status_code=201, tags=["Transfers"])
    def transfer(data: TransferCreate):
        """Atomically debit the source, credit the destination and persist both ledger entries."""
        return ledger.transfer(data)

    return app


app = create_app()
