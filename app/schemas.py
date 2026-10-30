from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExpenseCreate(BaseModel):
    """What the guest must fill in to add an expense."""

    description: str = Field(min_length=1, max_length=200, examples=["Hotel in Berlin"])
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["120.50"])
    currency: str = Field(min_length=3, max_length=3, examples=["EUR"])
    expense_date: date | None = Field(default=None, description="Defaults to today")

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()


class ExpenseUpdate(BaseModel):
    """What the guest can change later: only the description."""

    description: str = Field(min_length=1, max_length=200)


class ExpenseOut(BaseModel):
    """What the waiter brings back."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    amount: Decimal
    currency: str
    expense_date: date
    exchange_rate: Decimal
    rate_date: date
    amount_pln: Decimal
    created_at: datetime


class CurrencyTotal(BaseModel):
    currency: str
    count: int
    total: Decimal
    total_pln: Decimal


class Summary(BaseModel):
    total_pln: Decimal
    by_currency: list[CurrencyTotal]


class RateOut(BaseModel):
    currency: str
    rate: Decimal
    rate_date: date
    source: str = "NBP table A"