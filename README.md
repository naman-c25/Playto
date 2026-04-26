# Playto Payout Engine

A production-grade payout engine for the Playto Pay platform — handling merchant balance ledgers, payout requests, concurrency safety, and idempotent APIs.

> **Stack:** Django · PostgreSQL · Celery · Redis · React · Tailwind CSS · Docker

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  React Dashboard (port 3000)                                │
│  Polls /api/v1/ every 5s for live payout status updates     │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────────┐
│  Django + DRF (port 8000)                                   │
│  POST /api/v1/payouts/   ← idempotency gate + balance lock  │
│  GET  /api/v1/merchants/<id>/balance/                       │
│  GET  /api/v1/merchants/<id>/payouts/                       │
│  GET  /api/v1/merchants/<id>/ledger/                        │
└──────────────┬──────────────────────┬───────────────────────┘
               │ task.delay()         │ SELECT / INSERT
┌──────────────▼──────┐  ┌────────────▼──────────────────────┐
│  Redis (broker)     │  │  PostgreSQL                       │
│                     │  │  ├── merchants_merchant           │
└──────────────┬──────┘  │  ├── merchants_bankaccount        │
               │          │  ├── payouts_ledgerentry          │
┌──────────────▼──────┐  │  ├── payouts_payout               │
│  Celery Worker      │  │  └── payouts_idempotencykey        │
│  process_payout()   │  └───────────────────────────────────┘
│                     │
│  Celery Beat        │
│  detect_stuck_payouts (every 15s)
└─────────────────────┘
```

---

## Money Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Amount storage | `BigIntegerField` in paise | Floats cannot represent 0.1 exactly. Integer paise eliminates all rounding errors. |
| Balance computation | DB-level `SUM(CASE ...)` | Never fetch rows and sum in Python. The DB is the source of truth. |
| Held funds | Implicit via payout status | No hold/release ledger entries needed. `available = ledger_total - SUM(pending+processing)`. |
| Debit timing | On completion only | A DEBIT entry is only written when a payout succeeds. Failure simply changes status. |

---

## Quick Start (Docker)

```bash
git clone https://github.com/naman-c25/Playto
cd Playto
cp .env.example .env

docker-compose up --build
```

Services start at:
- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000/api/v1/
- **Django Admin:** http://localhost:8000/admin/

The `web` container auto-runs migrations and seeds the database on first start.

---

## Manual Setup (without Docker)

### Prerequisites
- Python 3.12+
- PostgreSQL 14+
- Redis 7+
- Node.js 20+

### Backend

```bash
cd backend

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Configure environment
cp ../.env.example .env            # edit DB_* and REDIS_URL

# Database
python manage.py migrate
python manage.py shell < scripts/seed.py

# Create Django superuser (optional, for /admin)
python manage.py createsuperuser

# Run services (3 terminals)
python manage.py runserver                                # API server
celery -A config.celery worker --loglevel=info           # Payout processor
celery -A config.celery beat --loglevel=info             # Periodic tasks
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:3000
```

---

## API Reference

All endpoints accept and return `application/json`.

### Merchant endpoints

```
GET /api/v1/merchants/
GET /api/v1/merchants/<id>/
GET /api/v1/merchants/<id>/balance/
GET /api/v1/merchants/<id>/payouts/
GET /api/v1/merchants/<id>/ledger/
```

### Payout endpoints

```
POST /api/v1/payouts/
GET  /api/v1/payouts/<id>/
GET  /api/v1/health/
```

### Creating a payout

```http
POST /api/v1/payouts/
X-Merchant-ID: 1
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json

{
  "amount_paise": 50000,
  "bank_account_id": 1
}
```

**Response (201 Created):**
```json
{
  "id": 42,
  "merchant_id": 1,
  "amount_paise": 50000,
  "amount_inr": "500.00",
  "status": "pending",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
  "attempt_count": 0,
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Error responses:**

| Status | Meaning |
|---|---|
| 400 | Missing or invalid Idempotency-Key / bad body |
| 401 | Missing X-Merchant-ID |
| 402 | Insufficient funds |
| 404 | Bank account not found |
| 409 | Same idempotency key is currently in-flight |

### Idempotency

Every `POST /api/v1/payouts/` requires an `Idempotency-Key: <UUID>` header. The same key returns the identical response. Clients should:

1. Generate a UUID v4 before the request.
2. Store it locally.
3. Retry with the **same key** on network failure.
4. Generate a new key only after a successful submission.

---

## Payout Lifecycle

```
POST /api/v1/payouts/
        │
        ▼
    [PENDING] ─── funds held (implicit)
        │
        ▼  Celery worker picks up
  [PROCESSING] ─── processing_started_at recorded
        │
    ┌───┴────────────────────────────────┐
    │ 70% success                        │ 20% failure         10% hang
    ▼                                    ▼                          │
[COMPLETED]                          [FAILED]          detect_stuck_payouts
Debit ledger entry written     Hold released via          retries after 5s/25s
atomically with status change  status change only         fails after 3 attempts
```

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

Key test cases:
- **`test_concurrent_payout_requests_exactly_one_succeeds`** — two threads, 60+60 on 100 balance. Only one wins.
- **`test_same_idempotency_key_returns_same_response`** — identical response, single payout created.
- **`test_held_balance_reduces_available_for_concurrent_request`** — held funds block overdraw.
- **`test_expired_idempotency_key_is_treated_as_fresh`** — 24h TTL is enforced.

---

## Project Structure

```
playto-payout-engine/
├── backend/
│   ├── config/
│   │   ├── settings/          # base / local / production
│   │   ├── celery.py          # Celery app + beat schedule
│   │   └── urls.py
│   ├── apps/
│   │   ├── merchants/         # Merchant, BankAccount
│   │   └── payouts/
│   │       ├── models.py      # LedgerEntry, Payout, IdempotencyKey
│   │       ├── state_machine.py   # transition() + VALID_TRANSITIONS
│   │       ├── exceptions.py
│   │       ├── views.py       # concurrency + idempotency logic
│   │       └── tasks.py       # process_payout, detect_stuck_payouts
│   ├── tests/
│   │   ├── test_concurrency.py
│   │   └── test_idempotency.py
│   └── scripts/seed.py
├── frontend/
│   └── src/
│       ├── components/        # BalanceCards, PayoutForm, PayoutTable, LedgerTable
│       ├── hooks/usePolling.js
│       └── api/client.js
├── docker-compose.yml
├── EXPLAINER.md
└── README.md
```

---

## Seeded Test Data

After running the seed script, three merchants are available:

| ID | Merchant | Balance |
|---|---|---|
| 1 | Arjun Sharma Design Studio | ~₹15,000–40,000 |
| 2 | Priya Nair Consulting | ~₹15,000–40,000 |
| 3 | Devbridge Software LLP | ~₹15,000–40,000 |

Each has 2 completed payouts, 1 failed payout, and a full credit history.
