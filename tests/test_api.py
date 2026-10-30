from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.nbp import CurrencyNotSupported, NBPClient, Rate, get_nbp_client


class FakeNBP:
    """A toy phone: always gives the same rates, never touches the internet."""

    RATES = {"EUR": Decimal("4.30"), "USD": Decimal("3.95")}

    def get_rate(self, currency: str, on: date | None = None) -> Rate:
        currency = currency.upper()
        if currency == "PLN":
            return Rate("PLN", Decimal("1"), on or date.today())
        if currency not in self.RATES:
            raise CurrencyNotSupported(f"No rate for {currency}")
        return Rate(currency, self.RATES[currency], on or date.today())


@pytest.fixture
def client():
    # A brand-new database that lives only in memory, for this one test.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    # Swap the real notebook and the real phone for test versions.
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_nbp_client] = FakeNBP

    with TestClient(app) as c:
        yield c

    # Put everything back after the test.
    app.dependency_overrides.clear()


# ---------- Tests of our API ----------

def test_create_expense_converts_to_pln(client):
    r = client.post(
        "/expenses",
        json={"description": "Hotel", "amount": "100.00", "currency": "eur",
              "expense_date": "2026-10-20"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["currency"] == "EUR"
    assert Decimal(body["amount_pln"]) == Decimal("430.00")
    assert Decimal(body["exchange_rate"]) == Decimal("4.30")


def test_unsupported_currency_returns_422(client):
    r = client.post("/expenses", json={"description": "x", "amount": "1", "currency": "XYZ"})
    assert r.status_code == 422


def test_invalid_amount_rejected(client):
    r = client.post("/expenses", json={"description": "x", "amount": "-5", "currency": "EUR"})
    assert r.status_code == 422


def test_crud_flow(client):
    created = client.post(
        "/expenses", json={"description": "Taxi", "amount": "20", "currency": "USD"}
    ).json()
    eid = created["id"]

    assert client.get(f"/expenses/{eid}").status_code == 200

    r = client.patch(f"/expenses/{eid}", json={"description": "Airport taxi"})
    assert r.json()["description"] == "Airport taxi"

    assert client.delete(f"/expenses/{eid}").status_code == 204
    assert client.get(f"/expenses/{eid}").status_code == 404


def test_list_filters_by_currency(client):
    client.post("/expenses", json={"description": "a", "amount": "10", "currency": "EUR"})
    client.post("/expenses", json={"description": "b", "amount": "10", "currency": "USD"})
    r = client.get("/expenses", params={"currency": "eur"})
    assert [e["currency"] for e in r.json()] == ["EUR"]


def test_summary(client):
    client.post("/expenses", json={"description": "a", "amount": "10", "currency": "EUR"})
    client.post("/expenses", json={"description": "b", "amount": "20", "currency": "EUR"})
    client.post("/expenses", json={"description": "c", "amount": "50", "currency": "PLN"})
    body = client.get("/expenses/summary").json()
    assert Decimal(body["total_pln"]) == Decimal("179.00")  # 30 * 4.30 + 50
    eur = next(c for c in body["by_currency"] if c["currency"] == "EUR")
    assert eur["count"] == 2


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


# ---------- Tests of the telephone itself, with NBP faked by respx ----------

@respx.mock
def test_nbp_client_takes_latest_rate_in_range():
    respx.get(url__regex=r".*/exchangerates/rates/a/eur/.*").mock(
        return_value=httpx.Response(200, json={
            "table": "A", "currency": "euro", "code": "EUR",
            "rates": [
                {"no": "206/A/NBP/2026", "effectiveDate": "2026-10-22", "mid": 4.2512},
                {"no": "207/A/NBP/2026", "effectiveDate": "2026-10-23", "mid": 4.2601},
            ],
        })
    )
    rate = NBPClient(base_url="https://api.nbp.pl/api").get_rate("EUR", date(2026, 10, 25))
    assert rate.rate == Decimal("4.2601")
    assert rate.rate_date == date(2026, 10, 23)  # Sunday -> falls back to Friday


@respx.mock
def test_nbp_client_404_means_unsupported():
    respx.get(url__regex=r".*/exchangerates/.*").mock(return_value=httpx.Response(404))
    with pytest.raises(CurrencyNotSupported):
        NBPClient(base_url="https://api.nbp.pl/api").get_rate("XYZ")