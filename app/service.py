from datetime import datetime, timezone
from decimal import Decimal

from app.db import MAX_CENTS, Database
from app.errors import APIError
from app.schemas import TransactionCreate, TransferCreate


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def money(cents: int):
    return f"{cents // 100}.{cents % 100:02d}"


def cents(amount: Decimal):
    return int(amount * 100)


def account_result(row):
    result = dict(row)
    result["balance"] = money(result.pop("balance_cents"))
    return result


def transaction_result(row):
    result = dict(row)
    result["amount"] = money(result.pop("amount_cents"))
    result["balance_after"] = money(result.pop("balance_after_cents"))
    return result


def require_account(conn, account_id):
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise APIError(404, "account_not_found", f"Account {account_id} was not found.")
    return row


def check_reference(conn, account_id, reference):
    if conn.execute(
        "SELECT 1 FROM transactions WHERE account_id = ? AND reference_id = ?",
        (account_id, reference),
    ).fetchone():
        raise APIError(
            409,
            "duplicate_transaction",
            f"Reference '{reference}' already exists for account {account_id}.",
        )


def change_balance(conn, account_id, delta):
    updated = conn.execute(
        "UPDATE accounts SET balance_cents = balance_cents + ? "
        "WHERE id = ? AND balance_cents + ? BETWEEN 0 AND ?",
        (delta, account_id, delta, MAX_CENTS),
    )
    if updated.rowcount != 1:
        if delta < 0:
            raise APIError(409, "insufficient_balance", "Account has insufficient balance.")
        raise APIError(
            409, "balance_limit_exceeded", "Credit would exceed the maximum account balance."
        )
    return require_account(conn, account_id)["balance_cents"]


def insert_transaction(
    conn, account_id, kind, amount, balance, reference, timestamp, transfer_id=None
):
    cursor = conn.execute(
        "INSERT INTO transactions "
        "(account_id, type, amount_cents, balance_after_cents, reference_id, transfer_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account_id, kind, amount, balance, reference, transfer_id, timestamp),
    )
    return transaction_result(
        conn.execute("SELECT * FROM transactions WHERE id = ?", (cursor.lastrowid,)).fetchone()
    )


class Ledger:
    def __init__(self, db: Database):
        self.db = db

    def create_account(self, name):
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO accounts(name, created_at) VALUES (?, ?)", (name, now())
            )
            return account_result(require_account(conn, cursor.lastrowid))

    def get_account(self, account_id):
        with self.db.connection() as conn:
            return account_result(require_account(conn, account_id))

    def list_accounts(self, page, page_size):
        with self.db.transaction(write=False) as conn:
            total = conn.execute("SELECT count(*) FROM accounts").fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY id DESC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
            return self.page([account_result(row) for row in rows], total, page, page_size)

    def create_transaction(self, data: TransactionCreate):
        with self.db.transaction() as conn:
            require_account(conn, data.account_id)
            check_reference(conn, data.account_id, data.reference_id)
            amount = cents(data.amount)
            balance = change_balance(
                conn, data.account_id, amount if data.type == "credit" else -amount
            )
            return insert_transaction(
                conn, data.account_id, data.type, amount, balance, data.reference_id, now()
            )

    def list_transactions(self, account_id, page, page_size):
        # Count and records share a read snapshot, even while other requests write.
        with self.db.transaction(write=False) as conn:
            require_account(conn, account_id)
            total = conn.execute(
                "SELECT count(*) FROM transactions WHERE account_id = ?", (account_id,)
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM transactions WHERE account_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (account_id, page_size, (page - 1) * page_size),
            ).fetchall()
            return self.page([transaction_result(row) for row in rows], total, page, page_size)

    def transfer(self, data: TransferCreate):
        with self.db.transaction() as conn:
            require_account(conn, data.source_account_id)
            require_account(conn, data.destination_account_id)
            # Each leg uses the same reference, scoped to its own account.
            for account_id in (data.source_account_id, data.destination_account_id):
                check_reference(conn, account_id, data.reference_id)
            amount = cents(data.amount)
            timestamp = now()
            source_balance = change_balance(conn, data.source_account_id, -amount)
            destination_balance = change_balance(conn, data.destination_account_id, amount)
            cursor = conn.execute(
                "INSERT INTO transfers(source_account_id, destination_account_id, amount_cents, reference_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    data.source_account_id,
                    data.destination_account_id,
                    amount,
                    data.reference_id,
                    timestamp,
                ),
            )
            transfer_id = cursor.lastrowid
            debit = insert_transaction(
                conn,
                data.source_account_id,
                "debit",
                amount,
                source_balance,
                data.reference_id,
                timestamp,
                transfer_id,
            )
            credit = insert_transaction(
                conn,
                data.destination_account_id,
                "credit",
                amount,
                destination_balance,
                data.reference_id,
                timestamp,
                transfer_id,
            )
            return {
                "id": transfer_id,
                "source_account_id": data.source_account_id,
                "destination_account_id": data.destination_account_id,
                "amount": money(amount),
                "reference_id": data.reference_id,
                "created_at": timestamp,
                "debit_transaction": debit,
                "credit_transaction": credit,
            }

    @staticmethod
    def page(data, total, page, page_size):
        return {
            "data": data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
        }
