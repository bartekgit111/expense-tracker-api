from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ExpenseCreate(BaseModel):
    """What the guest must fill in to add an expense."""

    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    expense_date: date | None = None


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
    created_at: datetime