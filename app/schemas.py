from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ExpenseCreate(BaseModel):
    """What the guest must fill in to add an expense."""

    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    expense_date: date | None = None

class ExpensesOut(BaseModel):
    """What the waiter brings back: the form plus things he added himself."""

    id: int
    description: str
    amount: Decimal
    currency: str
    expense_date: date
