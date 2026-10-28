from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db import MAX_CENTS, Database
from app.errors import APIError
from app.schemas import TransactionCreate, TransferCreate


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def money(cents: int):
    cents = int(cents)
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
        "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
        (account_id, kind, amount, balance, reference, transfer_id, timestamp),
    )
    return transaction_result(
        conn.execute("SELECT * FROM transactions WHERE id = ?", (cursor.fetchone()[0],)).fetchone()
    )


class Ledger:
    def __init__(self, db: Database):
        self.db = db

    def create_account(self, name):
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO accounts(name, created_at) VALUES (?, ?) RETURNING id", (name, now())
            )
            return account_result(require_account(conn, cursor.fetchone()[0]))

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
                "INSERT INTO transfers(source_account_id, destination_account_id, amount_cents, reference_id, created_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (
                    data.source_account_id,
                    data.destination_account_id,
                    amount,
                    data.reference_id,
                    timestamp,
                ),
            )
            transfer_id = cursor.fetchone()[0]
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

    def overview(self):
        with self.db.transaction(write=False) as conn:
            accounts = conn.execute(
                "SELECT count(*) AS account_count, coalesce(sum(balance_cents), 0) AS total_balance FROM accounts"
            ).fetchone()
            totals = conn.execute(
                "SELECT count(*) AS transaction_count, coalesce(sum(CASE WHEN type = 'credit' THEN amount_cents ELSE 0 END), 0) AS credited, coalesce(sum(CASE WHEN type = 'debit' THEN amount_cents ELSE 0 END), 0) AS debited FROM transactions"
            ).fetchone()
            first_day = (datetime.now(timezone.utc) - timedelta(days=6)).date()
            rows = conn.execute(
                "SELECT substr(created_at, 1, 10) AS day, type, sum(amount_cents) AS amount FROM transactions WHERE created_at >= ? GROUP BY substr(created_at, 1, 10), type",
                (first_day.isoformat(),),
            ).fetchall()
            daily = {(row["day"], row["type"]): row["amount"] for row in rows}
            return {
                "total_balance": money(accounts[1]),
                "account_count": accounts[0],
                "transaction_count": totals[0],
                "credited": money(totals[1]),
                "debited": money(totals[2]),
                "daily": [
                    {
                        "date": (first_day + timedelta(days=i)).isoformat(),
                        "credit": money(
                            daily.get(((first_day + timedelta(days=i)).isoformat(), "credit"), 0)
                        ),
                        "debit": money(
                            daily.get(((first_day + timedelta(days=i)).isoformat(), "debit"), 0)
                        ),
                    }
                    for i in range(7)
                ],
            }

    def activity(self, query):
        clauses, values = [], []
        if query.account_id is not None:
            clauses.append("t.account_id = ?")
            values.append(query.account_id)
        if query.type is not None:
            clauses.append("t.type = ?")
            values.append(query.type)
        if query.q:
            escaped = query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(
                "(lower(t.reference_id) LIKE lower(?) ESCAPE '\\' OR lower(a.name) LIKE lower(?) ESCAPE '\\')"
            )
            values.extend([f"%{escaped}%"] * 2)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        join = " FROM transactions t JOIN accounts a ON a.id = t.account_id"
        with self.db.transaction(write=False) as conn:
            if query.account_id is not None:
                require_account(conn, query.account_id)
            total = conn.execute("SELECT count(*)" + join + where, values).fetchone()[0]
            rows = conn.execute(
                "SELECT t.*, a.name AS account_name"
                + join
                + where
                + " ORDER BY t.id DESC LIMIT ? OFFSET ?",
                [*values, query.page_size, (query.page - 1) * query.page_size],
            ).fetchall()
            return self.page(
                [transaction_result(row) for row in rows], total, query.page, query.page_size
            )

    def seed_demo(self):
        # Deliberately only seed an empty workspace; never reset visitor data.
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
                return False
            samples = [("Operating", 1_824_000), ("Reserve", 825_000), ("Growth Fund", 420_000)]
            account_ids = []
            for name, amount in samples:
                timestamp = (
                    (datetime.now(timezone.utc) - timedelta(days=6))
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                cursor = conn.execute(
                    "INSERT INTO accounts(name, created_at) VALUES (?, ?) RETURNING id",
                    (name, timestamp),
                )
                account_id = cursor.fetchone()[0]
                account_ids.append(account_id)
                updated = change_balance(conn, account_id, amount)
                insert_transaction(
                    conn,
                    account_id,
                    "credit",
                    amount,
                    updated,
                    f"DEMO-OPEN-{account_id}",
                    timestamp,
                )
            movements = [
                (5, 0, "debit", 128_000, "SUPPLIER-1042"),
                (5, 1, "credit", 250_000, "RESERVE-TOPUP"),
                (4, 0, "credit", 452_000, "CLIENT-ACME-018"),
                (3, 2, "debit", 48_000, "SOFTWARE-ANNUAL"),
                (2, 0, "debit", 210_000, "TEAM-PAYROLL"),
                (1, 1, "debit", 75_000, "OFFICE-LEASE"),
                (0, 0, "credit", 178_000, "CLIENT-NOVA-024"),
                (0, 2, "credit", 96_000, "INVESTMENT-RETURN"),
            ]
            for days, index, kind, amount, reference in movements:
                account_id = account_ids[index]
                timestamp = (
                    (datetime.now(timezone.utc) - timedelta(days=days, hours=1))
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                updated = change_balance(conn, account_id, amount if kind == "credit" else -amount)
                insert_transaction(conn, account_id, kind, amount, updated, reference, timestamp)
            return True

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
