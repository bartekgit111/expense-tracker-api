from contextlib import asynccontextmanager
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.models import Expense
from app.nbp import CurrencyNotSupported, ExchangeRateUnavailable, NBPClient, get_nbp_client
from app.schemas import (
    CurrencyTotal,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
    RateOut,
    Summary,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Expense Tracker API",
    description=(
        "Multi-currency expense tracker. Each expense is converted to PLN "
        "using official NBP exchange rates for the expense date."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def get_rate_or_http_error(nbp: NBPClient, currency: str, on: date | None):
    try:
        return nbp.get_rate(currency, on)
    except CurrencyNotSupported as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def get_expense_or_404(db: Session, expense_id: int) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Expense {expense_id} not found")
    return expense


@app.get("/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/rates/{currency}", response_model=RateOut, tags=["rates"])
def get_rate(
    currency: str,
    on: date | None = Query(default=None, description="Date, defaults to today"),
    nbp: NBPClient = Depends(get_nbp_client),
):
    rate = get_rate_or_http_error(nbp, currency, on)
    return RateOut(currency=rate.currency, rate=rate.rate, rate_date=rate.rate_date)


@app.post(
    "/expenses",
    response_model=ExpenseOut,
    status_code=status.HTTP_201_CREATED,
    tags=["expenses"],
)
def create_expense(
    payload: ExpenseCreate,
    db: Session = Depends(get_db),
    nbp: NBPClient = Depends(get_nbp_client),
):
    expense_date = payload.expense_date or date.today()
    rate = get_rate_or_http_error(nbp, payload.currency, expense_date)

    expense = Expense(
        description=payload.description,
        amount=payload.amount,
        currency=payload.currency,
        expense_date=expense_date,
        exchange_rate=rate.rate,
        rate_date=rate.rate_date,
        amount_pln=(payload.amount * rate.rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        # amount_pln=(payload.amount + rate.rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@app.get("/expenses", response_model=list[ExpenseOut], tags=["expenses"])
def list_expenses(
    currency: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc())
    if currency:
        query = query.where(Expense.currency == currency.upper())
    return db.scalars(query.limit(limit).offset(offset)).all()


@app.get("/expenses/summary", response_model=Summary, tags=["expenses"])
def summary(db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            Expense.currency,
            func.count(Expense.id),
            func.sum(Expense.amount),
            func.sum(Expense.amount_pln),
        )
        .group_by(Expense.currency)
        .order_by(Expense.currency)
    ).all()

    by_currency = [
        CurrencyTotal(
            currency=cur,
            count=count,
            total=Decimal(total).quantize(Decimal("0.01")),
            total_pln=Decimal(total_pln).quantize(Decimal("0.01")),
        )
        for cur, count, total, total_pln in rows
    ]
    total_pln = sum((c.total_pln for c in by_currency), Decimal("0.00"))
    return Summary(total_pln=total_pln, by_currency=by_currency)


@app.get("/expenses/{expense_id}", response_model=ExpenseOut, tags=["expenses"])
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    return get_expense_or_404(db, expense_id)


@app.patch("/expenses/{expense_id}", response_model=ExpenseOut, tags=["expenses"])
def update_expense(expense_id: int, payload: ExpenseUpdate, db: Session = Depends(get_db)):
    expense = get_expense_or_404(db, expense_id)
    expense.description = payload.description
    db.commit()
    db.refresh(expense)
    return expense


@app.delete(
    "/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["expenses"]
)
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = get_expense_or_404(db, expense_id)
    db.delete(expense)
    db.commit()