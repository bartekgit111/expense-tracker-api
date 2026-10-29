from fastapi import FastAPI

app = FastAPI(title="Expense tracker API")


@app.get("/")
def hello():
    return {"message": "Hi! The restaurant is open."}


@app.get("/health")
def health():
    return {"status": "ok"}
