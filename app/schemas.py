import re
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.db import MAX_CENTS


def valid_money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Amount must be a decimal string or JSON number.")
    if isinstance(value, str) and (len(value) > 32 or not value.isascii()):
        raise ValueError("Amount must be a short ASCII decimal value.")
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(valid_money),
    Field(gt=0, le=Decimal(MAX_CENTS) / 100, max_digits=14, decimal_places=2),
]
Name = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100)
]
Reference = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)
]
AccountId = Annotated[int, Field(strict=True, gt=0, le=9_223_372_036_854_775_807)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountCreate(Input):
    name: Name


class TransactionCreate(Input):
    account_id: AccountId
    type: Literal["credit", "debit"]
    amount: Money
    reference_id: Reference


class TransferCreate(Input):
    source_account_id: AccountId
    destination_account_id: AccountId
    amount: Money
    reference_id: Reference

    @model_validator(mode="after")
    def different_accounts(self):
        if self.source_account_id == self.destination_account_id:
            raise ValueError("Source and destination accounts must differ.")
        return self


def positive_integer(value):
    if isinstance(value, str) and not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("Must be a positive integer without decimals or leading zeros.")
    return value


class PaginationQuery(Input):
    page: Annotated[int, BeforeValidator(positive_integer), Field(ge=1, le=1_000_000_000)] = 1
    page_size: Annotated[int, BeforeValidator(positive_integer), Field(ge=1, le=100)] = 20


class Account(BaseModel):
    id: int
    name: str
    balance: str = Field(examples=["100.00"])
    created_at: str


class Transaction(BaseModel):
    id: int
    account_id: int
    type: Literal["credit", "debit"]
    amount: str
    balance_after: str
    reference_id: str
    transfer_id: int | None
    created_at: str


class Transfer(BaseModel):
    id: int
    source_account_id: int
    destination_account_id: int
    amount: str
    reference_id: str
    created_at: str
    debit_transaction: Transaction
    credit_transaction: Transaction


class Pagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    data: list[T]
    pagination: Pagination
