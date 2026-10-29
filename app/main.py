from datetime import date

from fastapi import FastAPI, HTTPException, status

from app.schemas import ExpenseCreate, ExpensesOut

app = FastAPI(title="Expense tracker API")

# The waiter's memory: a list of expenses and a counter for numbering them.
# (In stage 3 this becomes a real database.)

expenses: list[ExpensesOut] = []
next_id=1


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/expenses", response_model=ExpensesOut, status_code=status.HTTP_201_CREATED)
def create_expense(payload: ExpenseCreate):
    global next_id

    expense = ExpensesOut(
        id = next_id,
        description=payload.description,
        amount=payload.amount,
        currency=payload.currency.upper(),
        expense_date=payload.expense_date or date.today()
    )

    expenses.append(expense)

    next_id+=1
    return expense


@app.get("/expenses", response_model=list[ExpensesOut])
def list_expenses():
    return expenses


@app.get("/expenses/{expense_id}",response_model=ExpensesOut)
def get_expense(expense_id: int):
    for expense in expenses:
        if expense.id == expense_id:
            return expense
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Expense {expense_id} not found")


@app.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense_id: int):
    for expense in expenses:
        if expense.id == expense_id:
            expenses.remove(expense)
            return
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Expense {expense_id} not found")
