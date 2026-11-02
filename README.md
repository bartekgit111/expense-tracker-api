# Expense Tracker API

A multi-currency expense tracking REST API built with **FastAPI**, **PostgreSQL** and the
**National Bank of Poland (NBP) exchange-rate API**, containerised with **Docker** and deployed
on **Google Cloud Run** with **Cloud SQL**.

Every expense is stored in its original currency and automatically converted to Polish złoty
(PLN) using the official NBP average exchange rate for the date of the expense. The rate used
is stored with the expense, so historical amounts never change and every conversion can be
traced back to its source.

---

## Table of contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Tech stack](#tech-stack)
4. [Project structure](#project-structure)
5. [Data model](#data-model)
6. [API reference](#api-reference)
7. [NBP integration](#nbp-integration)
8. [Error handling](#error-handling)
9. [Design decisions](#design-decisions)
10. [Running locally](#running-locally)
11. [Testing](#testing)
12. [Running with Docker](#running-with-docker)
13. [Deploying to Google Cloud](#deploying-to-google-cloud)
14. [Security](#security)
15. [Cost and cleanup](#cost-and-cleanup)
16. [Limitations and possible improvements](#limitations-and-possible-improvements)
17. [Screenshots](#screenshots)

---

## Features

- **Full CRUD for expenses**: create, list, read, update and delete expenses through a REST API.
- **Automatic currency conversion**: each expense is converted to PLN using the official NBP
  rate for its date.
- **Weekend and holiday handling**: NBP publishes rates only on working days; the API
  automatically uses the most recent rate published on or before the expense date.
- **Input validation**: positive amounts, at most two decimal places, three-letter currency
  codes and non-empty descriptions are enforced before any business logic runs.
- **Filtering and pagination**: list expenses by currency, with `limit` and `offset`.
- **Spending summary**: totals per currency and a grand total in PLN, computed in the
  database with `GROUP BY`.
- **Exchange-rate lookup endpoint**: query the NBP rate for any currency and date.
- **Health check**: verifies that both the service and the database are reachable.
- **Interactive documentation**: OpenAPI/Swagger UI generated automatically at `/docs`.
- **Automated tests**: 9 tests covering the API and the NBP client, running offline in under a second.
- **Containerised**: Docker image and Docker Compose setup with PostgreSQL.
- **Cloud deployment**: Cloud Run + Cloud SQL, with secrets in Secret Manager and a dedicated
  least-privilege service account.

---

## Architecture

```
                         ┌────────────────────── Google Cloud (europe-central2, Warsaw) ──────────────────────┐
                         │                                                                                     │
   Client                │   ┌────────────────────────────┐   Unix socket    ┌──────────────────────────┐     │
 (browser, curl,  HTTPS  │   │  Cloud Run                 │  /cloudsql/...   │  Cloud SQL               │     │
  PowerShell)  ──────────┼──►│  FastAPI app in Docker     │ ───────────────► │  PostgreSQL 16           │     │
                         │   │  (scales 0 → 2 instances)  │                  │  database: expenses      │     │
                         │   └──────┬──────────────▲──────┘                  └──────────────────────────┘     │
                         │          │              │                                                         │
                         │          │              │ DATABASE_URL injected at startup                        │
                         │          │       ┌──────┴───────────────┐                                         │
                         │          │       │  Secret Manager      │                                         │
                         │          │       └──────────────────────┘                                         │
                         │          │                                                                         │
                         │          │   runs as service account expense-tracker-sa                           │
                         │          │   (roles: cloudsql.client, secretAccessor on one secret)               │
                         └──────────┼──────────────────────────────────────────────────────────────────────────┘
                                    │ HTTPS
                                    ▼
                          NBP public API (api.nbp.pl)
```

Build and delivery pipeline:

```
 Source code ──► Cloud Build (builds Dockerfile) ──► Artifact Registry (image) ──► Cloud Run (deploy)
```

### Request flow: creating an expense

1. The client sends `POST /expenses` with a description, amount, currency and optional date.
2. **Pydantic** validates the body against the `ExpenseCreate` schema. Invalid input is
   rejected with `422` before any code in the endpoint runs.
3. FastAPI injects a **database session** (`get_db`) and an **NBP client** (`get_nbp_client`)
   through dependency injection.
4. The NBP client asks the NBP API for rates in the 10 days up to the expense date and picks
   the most recent one.
5. The amount is converted to PLN using `Decimal` arithmetic and rounded half-up to 2 decimal places.
6. The expense, the rate used, the rate's date and the PLN amount are saved in one transaction.
7. The API returns `201 Created` with the full record.

---

## Tech stack

| Area | Technology |
|---|---|
| Language | Python 3.11 |
| Web framework | FastAPI, Uvicorn (ASGI server) |
| Validation and serialisation | Pydantic v2 |
| Database access | SQLAlchemy 2.0 ORM |
| Databases | SQLite (local development), PostgreSQL 16 (Docker and Cloud SQL) |
| PostgreSQL driver | psycopg 3 |
| HTTP client | httpx |
| Testing | pytest, respx (HTTP mocking), FastAPI `TestClient` |
| Containers | Docker, Docker Compose |
| Cloud | Google Cloud Run, Cloud SQL, Artifact Registry, Cloud Build, Secret Manager, IAM |
| CI | GitHub Actions |
| Version control | Git, feature branches |

---

## Project structure

```
expense-tracker/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, lifespan, all REST endpoints
│   ├── db.py            # SQLAlchemy engine, session factory, get_db dependency
│   ├── models.py        # ORM model: the expenses table
│   ├── schemas.py       # Pydantic request/response schemas and validation rules
│   └── nbp.py           # NBP exchange-rate API client and custom exceptions
├── tests/
│   └── test_api.py      # API tests with a fake NBP client; NBP client tests with respx
├── docs/
│   └── screenshots/     # Screenshots of the live deployment
├── .github/
│   └── workflows/
│       └── ci.yml       # GitHub Actions: run tests, then build the Docker image
├── Dockerfile           # Production image (python:3.11-slim, non-root user)
├── .dockerignore        # Files excluded from the Docker build context
├── docker-compose.yml   # Local stack: API + PostgreSQL with a persistent volume
├── requirements.txt     # Runtime dependencies
├── requirements-dev.txt # Runtime + test dependencies
├── pytest.ini           # pytest configuration
├── .gitignore
└── README.md
```

### Responsibilities of each module

- **`main.py`**: the HTTP layer. Defines endpoints, maps domain errors to HTTP status codes,
  and creates tables on startup through FastAPI's `lifespan` hook.
- **`db.py`**: reads `DATABASE_URL` from the environment (falling back to a local SQLite file),
  creates the engine, and provides `get_db()`, which opens one session per request and always
  closes it.
- **`models.py`**: how data is **stored** (columns, types, indexes).
- **`schemas.py`**: what goes **in and out** of the API (validation, examples for `/docs`).
- **`nbp.py`**: everything about talking to NBP. It knows nothing about HTTP status codes for
  our own clients, so it can be tested and reused independently.

---

## Data model

Table **`expenses`**:

| Column | Type | Description |
|---|---|---|
| `id` | integer, primary key | Assigned by the database |
| `description` | varchar(200) | What the expense was for |
| `amount` | numeric(12, 2) | Amount in the original currency |
| `currency` | varchar(3), indexed | ISO 4217 code, stored upper-case (e.g. `EUR`) |
| `expense_date` | date | Date of the expense (defaults to today) |
| `exchange_rate` | numeric(12, 6) | PLN per 1 unit of the currency, from NBP |
| `rate_date` | date | Date of the NBP rate actually used |
| `amount_pln` | numeric(12, 2) | `amount × exchange_rate`, rounded half-up |
| `created_at` | timestamp with time zone | When the record was created (UTC) |

The `currency` column is indexed because listing and summarising by currency are the most
common queries.

---

## API reference

Base URL locally: `http://127.0.0.1:8000`. Interactive documentation: **`/docs`** (Swagger UI)
and `/redoc`.

### Summary

| Method | Path | Description | Success |
|---|---|---|---|
| `GET` | `/health` | Service and database health check | `200` |
| `GET` | `/rates/{currency}` | NBP rate for a currency, optionally on a date | `200` |
| `POST` | `/expenses` | Create an expense, converted to PLN | `201` |
| `GET` | `/expenses` | List expenses, with filtering and pagination | `200` |
| `GET` | `/expenses/summary` | Totals per currency and overall in PLN | `200` |
| `GET` | `/expenses/{id}` | Get a single expense | `200` |
| `PATCH` | `/expenses/{id}` | Update an expense's description | `200` |
| `DELETE` | `/expenses/{id}` | Delete an expense | `204` |

### `GET /health`

Runs `SELECT 1` against the database.

```json
{ "status": "ok", "database": "ok" }
```

### `GET /rates/{currency}?on=YYYY-MM-DD`

| Parameter | In | Required | Description |
|---|---|---|---|
| `currency` | path | yes | Three-letter code, case-insensitive |
| `on` | query | no | Date; defaults to today |

```
GET /rates/usd?on=2026-10-25
```

```json
{
  "currency": "USD",
  "rate": "3.6512",
  "rate_date": "2026-10-23",
  "source": "NBP table A"
}
```

`2026-10-25` is a Sunday, so the rate from Friday `2026-10-23` is returned.

### `POST /expenses`

Request body:

| Field | Type | Rules |
|---|---|---|
| `description` | string | 1–200 characters |
| `amount` | decimal | greater than 0, at most 12 digits, at most 2 decimal places |
| `currency` | string | exactly 3 letters; converted to upper-case |
| `expense_date` | date, optional | defaults to today |

```json
{
  "description": "Hotel in Berlin",
  "amount": 120.50,
  "currency": "eur",
  "expense_date": "2026-10-20"
}
```

Response `201 Created`:

```json
{
  "id": 1,
  "description": "Hotel in Berlin",
  "amount": "120.50",
  "currency": "EUR",
  "expense_date": "2026-10-20",
  "exchange_rate": "4.271500",
  "rate_date": "2026-10-20",
  "amount_pln": "514.72",
  "created_at": "2026-11-02T11:45:12.123456Z"
}
```

(Rates in these examples are illustrative.)

### `GET /expenses`

| Query parameter | Default | Rules | Description |
|---|---|---|---|
| `currency` | none | 3 letters | Only expenses in this currency |
| `limit` | 50 | 1–500 | Maximum number of results |
| `offset` | 0 | ≥ 0 | Number of results to skip |

Results are ordered by `expense_date` descending, then `id` descending (newest first).

```
GET /expenses?currency=EUR&limit=10&offset=0
```

### `GET /expenses/summary`

```json
{
  "total_pln": "1023.47",
  "by_currency": [
    { "currency": "EUR", "count": 2, "total": "210.40", "total_pln": "898.70" },
    { "currency": "PLN", "count": 1, "total": "45.00",  "total_pln": "45.00"  },
    { "currency": "USD", "count": 1, "total": "22.00",  "total_pln": "79.77"  }
  ]
}
```

Amounts in different currencies cannot be added together, so each currency has its own total;
the grand total is the sum of the PLN amounts.

### `PATCH /expenses/{id}`

Only the description can be changed. Changing the amount, currency or date would require a new
exchange rate, so such a change is modelled as deleting and creating an expense.

```json
{ "description": "Hotel in Munich" }
```

### `DELETE /expenses/{id}`

Returns `204 No Content` on success.

### Example with PowerShell

```powershell
$URL = "http://127.0.0.1:8000"

Invoke-RestMethod -Method Post -Uri "$URL/expenses" -ContentType "application/json" `
  -Body (@{ description = "Taxi"; amount = 32.00; currency = "USD" } | ConvertTo-Json)

Invoke-RestMethod "$URL/expenses" | Format-Table id, description, amount, currency, amount_pln
Invoke-RestMethod "$URL/expenses/summary" | ConvertTo-Json -Depth 5
```

### Example with curl

```bash
curl -X POST http://127.0.0.1:8000/expenses \
  -H "Content-Type: application/json" \
  -d '{"description": "Taxi", "amount": "32.00", "currency": "USD"}'
```

---

## NBP integration

The application uses NBP's public **table A** (average exchange rates), documented at
<https://api.nbp.pl/en.html>. No API key is required.

Request made for each conversion:

```
GET https://api.nbp.pl/api/exchangerates/rates/a/{code}/{start}/{end}/?format=json
```

where `end` is the expense date and `start` is 10 days earlier. Example response:

```json
{
  "table": "A",
  "currency": "euro",
  "code": "EUR",
  "rates": [
    { "no": "206/A/NBP/2026", "effectiveDate": "2026-10-22", "mid": 4.2512 },
    { "no": "207/A/NBP/2026", "effectiveDate": "2026-10-23", "mid": 4.2601 }
  ]
}
```

The client takes the **last** element of `rates`, which is the most recent rate published on or
before the expense date.

### Why a date range instead of a single date?

NBP does not publish rates on weekends or public holidays; asking for a single such date returns
`404`. Requesting a 10-day window and taking the latest rate handles weekends and long holiday
breaks (e.g. Christmas) with a single request. This mirrors common accounting practice of using
the last available rate.

### Robustness

- **Timeout**: every request has a 5-second timeout, so a slow NBP cannot block the API indefinitely.
- **PLN shortcut**: converting PLN to PLN returns a rate of 1 without calling NBP.
- **Exact decimals**: the `mid` value is converted with `Decimal(str(value))` to avoid
  floating-point artefacts.
- **Configurable URL**: `NBP_API_URL` can be overridden through an environment variable, which
  is used to simulate an outage.

---

## Error handling

| Situation | Status | Example `detail` |
|---|---|---|
| Invalid request body or parameter (negative amount, empty description, wrong currency length, non-numeric id) | `422` | Pydantic validation details |
| Currency not published by NBP (e.g. `XYZ`) | `422` | `No NBP rate for XYZ between ...` |
| Expense with the given id does not exist | `404` | `Expense 999 not found` |
| NBP unreachable, timed out or returned an unexpected status | `503` | `Could not reach NBP API: ...` |

The NBP client raises domain-specific exceptions (`CurrencyNotSupported`,
`ExchangeRateUnavailable`). A small helper in `main.py` translates them into HTTP errors. This
keeps HTTP concerns out of the integration code and distinguishes **client errors** (`4xx`, the
caller should fix the request) from **upstream failures** (`503`, the caller can retry later).

When conversion fails, **nothing is saved**: the rate is fetched before the database transaction begins.

---

## Design decisions

- **`Decimal`, never `float`, for money.** Floating-point numbers cannot represent most decimal
  fractions exactly (`0.1 + 0.2 = 0.30000000000000004`). All amounts and rates use `Decimal`,
  and the database uses `NUMERIC`.
- **Explicit rounding.** PLN amounts are rounded with `ROUND_HALF_UP` to 2 decimal places, as
  is standard for currency.
- **Store the rate, not just the result.** Saving `exchange_rate` and `rate_date` makes every
  conversion auditable and reproducible, keeps historical totals stable, and means reads never
  depend on NBP being available.
- **Separate schemas and models.** Pydantic schemas define the API contract; SQLAlchemy models
  define storage. The client never chooses `id` or `created_at`, and the response includes
  computed fields that are not part of the input.
- **Dependency injection for external resources.** The database session and the NBP client are
  provided through `Depends(...)`. Tests replace them with an in-memory database and a fake
  client without changing application code.
- **Configuration through environment variables.** `DATABASE_URL` and `NBP_API_URL` follow the
  twelve-factor approach: the same image runs with SQLite, local PostgreSQL or Cloud SQL.
- **Route order.** `/expenses/summary` is declared before `/expenses/{expense_id}` so the literal
  path is matched before the parameterised one.
- **Bounded pagination.** `limit` is capped at 500 to protect the database from very large queries.
- **Schema creation on startup.** Tables are created with `Base.metadata.create_all()` in the
  `lifespan` hook. This is sufficient for a demo; a production system would use migrations (see below).

---

## Running locally

### Prerequisites

- Python 3.10 or newer (developed on 3.11)
- Git

### Setup

**Windows (PowerShell):**

```powershell
git clone https://github.com/bartekgit111/expense-tracker-api.git
cd expense-tracker-api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

If PowerShell blocks the activation script, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Linux / macOS:**

```bash
git clone https://github.com/bartekgit111/expense-tracker-api.git
cd expense-tracker-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open **<http://127.0.0.1:8000/docs>**.

Without `DATABASE_URL`, the app creates a SQLite file `expenses.db` in the project folder.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./expenses.db` | SQLAlchemy connection URL |
| `NBP_API_URL` | `https://api.nbp.pl/api` | Base URL of the NBP API |
| `PORT` | `8080` (in Docker) | Port Uvicorn listens on inside the container |

Example PostgreSQL URL: `postgresql+psycopg://user:password@localhost:5432/expenses`.

---

## Testing

```bash
pytest -v
```

```
tests/test_api.py::test_create_expense_converts_to_pln PASSED
tests/test_api.py::test_unsupported_currency_returns_422 PASSED
tests/test_api.py::test_invalid_amount_rejected PASSED
tests/test_api.py::test_crud_flow PASSED
tests/test_api.py::test_list_filters_by_currency PASSED
tests/test_api.py::test_summary PASSED
tests/test_api.py::test_health PASSED
tests/test_api.py::test_nbp_client_takes_latest_rate_in_range PASSED
tests/test_api.py::test_nbp_client_404_means_unsupported PASSED

9 passed in 0.6s
```

### Test strategy

The suite tests two layers independently:

1. **API behaviour** (7 tests). A `client` fixture creates a fresh **in-memory SQLite database**
   for each test (using `StaticPool` so all sessions share it) and overrides two dependencies:
   - `get_db` → a session bound to the in-memory database,
   - `get_nbp_client` → `FakeNBP`, which returns fixed rates (EUR 4.30, USD 3.95) and raises
     `CurrencyNotSupported` for anything else.

   Fixed rates make expected values exact (e.g. 100 EUR → 430.00 PLN), and tests never touch
   real data or the network.

2. **NBP client** (2 tests). The real `NBPClient` runs against **mocked HTTP responses** using
   `respx`, which intercepts `httpx` requests:
   - a weekend date must resolve to the previous Friday's rate,
   - a `404` from NBP must raise `CurrencyNotSupported`.

| Test | Verifies |
|---|---|
| `test_create_expense_converts_to_pln` | Conversion, upper-casing, stored rate |
| `test_unsupported_currency_returns_422` | Unknown currency is rejected |
| `test_invalid_amount_rejected` | Validation of negative amounts |
| `test_crud_flow` | Create → read → update → delete → 404 |
| `test_list_filters_by_currency` | Currency filter on the list endpoint |
| `test_summary` | Grouping, counts and grand total in PLN |
| `test_health` | Health endpoint and database connectivity |
| `test_nbp_client_takes_latest_rate_in_range` | Weekend fallback in the real client |
| `test_nbp_client_404_means_unsupported` | Error mapping in the real client |

### Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` and on pull requests:

1. **test**: installs dependencies on Ubuntu with Python 3.11 and runs `pytest`;
2. **docker-build**: runs only if the tests pass, and verifies that the Docker image builds.

---

## Running with Docker

### Single container (SQLite inside the container)

```bash
docker build -t expense-tracker .
docker run --rm -p 8000:8080 expense-tracker
```

Open <http://127.0.0.1:8000/docs>. Data is lost when the container is removed.

### Full stack with PostgreSQL (Docker Compose)

```bash
docker compose up --build
```

Open <http://127.0.0.1:8080/docs>.

`docker-compose.yml` defines two services:

- **`db`**: `postgres:16` with a named volume `pgdata` (data survives container restarts) and a
  `pg_isready` health check;
- **`api`**: built from the `Dockerfile`, with
  `DATABASE_URL=postgresql+psycopg://expenses:expenses@db:5432/expenses`. It starts only after
  the database reports healthy (`depends_on: condition: service_healthy`).

Containers reach each other by service name (`@db`). The credentials are for local development only.

```bash
docker compose down      # stop and remove containers, keep data
docker compose down -v   # also delete the database volume
```

### The Dockerfile

- Based on **`python:3.11-slim`** for a small image.
- **Dependencies are installed before the source code is copied**, so code changes reuse the
  cached dependency layer and rebuilds take seconds.
- Runs as an unprivileged **`appuser`**, not root; `/app` is owned by that user so SQLite can
  write its file.
- Listens on **`0.0.0.0:$PORT`** (default 8080), as Cloud Run expects.
- `.dockerignore` keeps the virtual environment, Git history, tests, local databases and secrets
  out of the build context (about 34 KB instead of hundreds of MB).

---

## Deploying to Google Cloud

The application was deployed to **Cloud Run** in `europe-central2` (Warsaw), backed by
**Cloud SQL for PostgreSQL**. The commands below are for PowerShell; replace the project ID
with your own.

### Prerequisites

- A Google Cloud project with billing enabled
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), logged in with `gcloud init`

### 1. Variables, region and APIs

```powershell
$PROJECT = "expense-tracker-bartosz"
$REGION  = "europe-central2"
gcloud config set project $PROJECT
gcloud config set run/region $REGION

gcloud services enable run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
```

### 2. Artifact Registry repository

```powershell
gcloud artifacts repositories create expense-tracker --repository-format=docker --location=$REGION
```

### 3. Cloud SQL instance, database and user

```powershell
gcloud sql instances create expense-tracker-db --database-version=POSTGRES_16 --edition=ENTERPRISE --tier=db-f1-micro --region=$REGION --storage-size=10GB
gcloud sql databases create expenses --instance=expense-tracker-db

$DB_PASS = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
gcloud sql users create expenses_app --instance=expense-tracker-db --password=$DB_PASS
```

`db-f1-micro` is the smallest shared-core tier. Instance creation takes 5–15 minutes.

### 4. Database URL in Secret Manager

```powershell
$CONN = gcloud sql instances describe expense-tracker-db --format="value(connectionName)"
$DATABASE_URL = "postgresql+psycopg://expenses_app:${DB_PASS}@/expenses?host=/cloudsql/$CONN"

[IO.File]::WriteAllText("$env:TEMP\dburl.txt", $DATABASE_URL)
gcloud secrets create expense-tracker-database-url --data-file="$env:TEMP\dburl.txt"
Remove-Item "$env:TEMP\dburl.txt"
```

On Cloud Run, the Cloud SQL instance is reachable through a Unix socket at
`/cloudsql/PROJECT:REGION:INSTANCE`, so the URL has no host or port; `?host=` points psycopg at the socket.

### 5. Runtime service account (least privilege)

```powershell
gcloud iam service-accounts create expense-tracker-sa --display-name="Expense Tracker runtime"
$SA = "expense-tracker-sa@$PROJECT.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/cloudsql.client" --condition=None
gcloud secrets add-iam-policy-binding expense-tracker-database-url --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"
```

### 6. Build the image with Cloud Build

In new projects, Cloud Build runs as the Compute Engine default service account, which has no
permissions by default. Grant it the builder role once (the project number appears in the
error message if it is missing, or via `gcloud projects describe $PROJECT`):

```powershell
$PROJECT_NUMBER = gcloud projects describe $PROJECT --format="value(projectNumber)"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" --role="roles/cloudbuild.builds.builder" --condition=None
```

Then build and push:

```powershell
$IMAGE = "$REGION-docker.pkg.dev/$PROJECT/expense-tracker/expense-tracker:latest"
gcloud builds submit --tag $IMAGE .
```

### 7. Deploy to Cloud Run

```powershell
gcloud run deploy expense-tracker `
  --image $IMAGE `
  --region $REGION `
  --service-account $SA `
  --add-cloudsql-instances $CONN `
  --set-secrets "DATABASE_URL=expense-tracker-database-url:latest" `
  --allow-unauthenticated `
  --min-instances 0 `
  --max-instances 2 `
  --memory 512Mi
```

| Flag | Purpose |
|---|---|
| `--service-account` | Run with the least-privilege identity created above |
| `--add-cloudsql-instances` | Mount the Cloud SQL Unix socket |
| `--set-secrets` | Inject the secret as the `DATABASE_URL` environment variable |
| `--allow-unauthenticated` | Public access |
| `--min-instances 0` | Scale to zero when idle (no cost at rest; first request has a cold start) |
| `--max-instances 2` | Cap concurrency and cost |

The command prints the service URL, e.g. `https://expense-tracker-<number>.europe-central2.run.app`.
Open `<URL>/docs` and `<URL>/health`.

---

## Security

- **No secrets in code or images.** The database password is generated randomly, stored only in
  Secret Manager, and injected into Cloud Run at runtime. `.env` and database files are excluded
  by `.gitignore` and `.dockerignore`.
- **Least-privilege IAM.** The runtime service account can only connect to Cloud SQL and read a
  single secret.
- **Private database connection.** Cloud Run connects to Cloud SQL through the Cloud SQL Unix
  socket; the instance's public IP has no authorised networks.
- **Non-root container.** The application runs as an unprivileged user.
- **Input validation** at the API boundary, and bounded pagination.
- **Timeouts** on all outbound HTTP calls.

The deployed API is intentionally **public and unauthenticated** for demonstration purposes;
see the improvements below.

---

## Cost and cleanup

Approximate costs in `europe-central2`:

| Service | Usage | Cost |
|---|---|---|
| Cloud SQL `db-f1-micro`, 10 GB | billed per hour while the instance exists | ~1.7 PLN/day (~50 PLN/month) |
| Cloud Run | scales to zero; light traffic | within the free tier |
| Cloud Build, Artifact Registry, Secret Manager | a few builds, one image, one secret | within free tiers |

The demo deployment was run for about 30 minutes and then removed:

```powershell
gcloud run services delete expense-tracker --region $REGION --quiet
gcloud sql instances delete expense-tracker-db --quiet
gcloud secrets delete expense-tracker-database-url --quiet
gcloud artifacts repositories delete expense-tracker --location $REGION --quiet
gcloud iam service-accounts delete "expense-tracker-sa@$PROJECT.iam.gserviceaccount.com" --quiet

gcloud sql instances list     # Listed 0 items.
gcloud run services list      # Listed 0 items.
```

Alternatively, delete the whole project: `gcloud projects delete $PROJECT`.

---

## Limitations and possible improvements

- **Database migrations**: replace `create_all()` with **Alembic**, so schema changes do not
  require recreating the database.
- **Authentication and authorisation**: API keys or OAuth 2.0 / OpenID Connect, with expenses
  owned by users.
- **Rate caching**: cache NBP rates per currency and date in the database or memory to avoid
  repeated calls.
- **Retries with backoff** for transient NBP failures.
- **Automated deployment**: deploy from GitHub Actions to Cloud Run using Workload Identity
  Federation (no long-lived keys).
- **Infrastructure as code**: describe the GCP resources with **Terraform**.
- **Production database settings**: automated backups, point-in-time recovery, high
  availability, private IP only.
- **Observability**: structured JSON logging, request IDs, Cloud Monitoring alerts.
- **Pinned dependencies** (`==` versions or a lock file) for fully reproducible builds.
- **Async database access** for higher concurrency.

---

## Screenshots

### API documentation served from Cloud Run

![API docs on Cloud Run](docs/screenshots/cloud-run-docs.png)

### Cloud Run service

![Cloud Run service](docs/screenshots/cloud-run-service.png)

### Cloud SQL instance

![Cloud SQL instance](docs/screenshots/cloud-sql-instance.png)

---

## Author

**Bartosz Chudek** — Mathematics & Data Science, Warsaw University of Technology
GitHub: [@bartekgit111](https://github.com/bartekgit111)
