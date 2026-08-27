# Everyticket Subscription Management Platform

Standalone subscription management application for Everyticket (plans,
registration, payments, subscription lifecycle, invoicing, Everyticket
integration, admin/customer portals). Everyticket itself - ticketing,
booking, POS, etc. - is a separate application and is out of scope here.

**Current status:** Phase 1 foundation, a working new-subscription ->
mock-payment -> active -> invoice flow, admin login + MFA, duplicate
customer detection + OTP verification, and customer-portal
upgrade/downgrade/renew/cancel - all backed by a real Postgres schema and
an 18-test automated suite (`pytest tests/ -v`), plus hand-verified via
curl against real Postgres. Still not built: admin CRUD API beyond login,
React frontend, PayU, Everyticket webhooks, SSO, email, background jobs.
See **[docs/implementation-status.md](docs/implementation-status.md)**
for the exact done/not-done breakdown and suggested next steps - read that
before assuming any given feature works.

## Architecture

Modular monolith: FastAPI + SQLAlchemy + Alembic + PostgreSQL backend,
React frontend (not yet scaffolded - corrected from Angular on 2026-08-27), Celery/Redis for background jobs,
Docker Compose for local development. See `backend/app/` for the module
layout (customers, plans, subscriptions, payments, invoices,
notifications, webhooks, integrations, sso, audit, auth [admin auth +
customer OTP], admin/customer/public API routers).

## Local development

### Option A: bare Python + your own Postgres

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example ../.env   # then edit DATABASE_URL etc. if needed
export DATABASE_URL="postgresql+psycopg2://subscription:subscription@localhost:5432/subscription"
export ENVIRONMENT=development
# Dev-only conveniences - never true in production (enforced backend-side
# regardless of these values, see app/core/config.py):
export ALLOW_OTP_BYPASS=true          # lets "BYPASS" satisfy customer OTP verification
export ALLOW_ADMIN_MFA_BYPASS=true    # lets "BYPASS" satisfy admin MFA verification
export TEST_MODE=true                 # surfaces the real OTP code in the /identify response body

alembic upgrade head          # apply migrations
python -m app.core.seed       # create EVERYTICKET application, Basic/Professional/Enterprise plans, dev admin user
uvicorn app.main:app --reload
```

`python -m app.core.seed` prints the dev admin login
(`admin@example.com` / `ChangeMe123!`) and its MFA secret/provisioning
URI to stdout - use those, or submit `"BYPASS"` as the MFA code, against
`POST /api/v1/admin/auth/login` then `POST /api/v1/admin/auth/mfa/verify`.

API docs: http://localhost:8000/docs (Swagger) or /redoc.

### Option B: Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Brings up postgres, redis, backend, worker, scheduler, and the frontend
placeholder. **Not yet verified in this pass** - see
docs/implementation-status.md for why (no Docker daemon available in the
environment this was built in). Run it once and sanity-check before
relying on it.

### Running tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

No external services required - the suite uses an in-memory SQLite
database and exercises the full mock-payment subscription flow.

### Useful commands

| Task | Command |
|---|---|
| New migration after model changes | `alembic revision --autogenerate -m "..."` |
| Apply migrations | `alembic upgrade head` |
| Seed dev data | `python -m app.core.seed` |
| Run backend | `uvicorn app.main:app --reload` |
| Run tests | `pytest tests/ -v` |
| Run worker (once Celery tasks exist) | `celery -A app.core.celery_app worker --loglevel=info` |

## Documentation

- [docs/implementation-status.md](docs/implementation-status.md) - what's
  built vs. spec, and the suggested order for continuing.

## Environment variables

See `.env.example` for the full list with comments. Never commit a real
`.env` file - it's gitignored.
