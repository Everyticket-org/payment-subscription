# Implementation status

Tracks progress against the Phase 1 acceptance criteria in the master
prompt (`docs/` doesn't yet have a copy of the full spec text - the
authoritative copy is saved in the "Subscription Project" on claude.ai as
`claude/master-dev-prompt-v1.md`; section numbers below refer to it).

This file is the single source of truth for "what's actually built vs.
what's still spec" - update it whenever a module moves from planned to
implemented.

## What's implemented (this pass)

**Foundation**
- Repo layout matching spec section 86 (backend modular monolith, frontend
  placeholder, infra, docs).
- Docker Compose for postgres/redis/backend/worker/scheduler/frontend
  (`docker-compose.yml`), `.env.example`, `.gitignore`.
- FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic Settings backend skeleton.

**Database**
- Full schema (27 tables) covering every entity in spec section 57:
  applications, customers, customer_application_mappings,
  customer_registration_data, plans, plan_features, plan_transitions,
  subscriptions, subscription_history, payment_transactions,
  payment_gateway_configs, invoices, invoice_items, webhook_events,
  webhook_deliveries, notification_templates, notification_logs,
  otp_sessions, sso_sessions, admin_users/roles/permissions, audit_logs,
  system_settings.
- Two Alembic migrations, generated and applied against a real local
  Postgres 16 instance during this build (not just SQLite): initial
  schema, then a partial unique index enforcing "one ACTIVE subscription
  per customer per application" (spec section 22) directly at the
  database level (`WHERE status = 'ACTIVE'`).
- Secure random public IDs (CUS-/SUB-/TXN-/INV-/EVT-/CORR-/OTP-/SSO-,
  spec section 21) via `app/core/ids.py`.

**Payment abstraction (spec sections 23-28, 74)**
- `PaymentGateway` ABC (`app/payments/interfaces/gateway.py`) with
  create_payment / get_payment_status / verify_payment / verify_webhook /
  process_webhook, plus recurring-payment hooks stubbed for future use.
- `MockPaymentGateway` implementing SUCCESS/FAILED/PENDING/TIMEOUT
  scenarios (spec section 24) through the same interface a real gateway
  adapter would use.
- Gateway registry (`app/payments/gateways/registry.py`) so adding a new
  gateway is: implement the interface, register it, configure
  credentials - no core-logic changes.
- `PaymentService.process_gateway_result()` is the single idempotency +
  financial-transaction-safety choke point (spec sections 28, 58):
  verified terminal payment states are never reprocessed, and
  payment -> subscription -> invoice all update in one DB transaction.

**Minimal "new subscription" flow (spec section 19)**
- `POST /api/v1/public/plans/{plan_code}/subscribe` - new customer,
  PENDING_PAYMENT subscription, payment transaction creation.
- `POST /api/v1/payment/mock/callback` - simulated gateway callback that
  drives payment SUCCESS -> subscription ACTIVE -> invoice generated,
  through the exact code path a real PayU webhook will use once that
  adapter exists.
- `GET /api/v1/public/plans`, `GET /api/v1/public/plans/{code}`.
- `/health`, `/ready` (spec section 83).
- Structured `AppError` exception hierarchy (spec section 63) -> consistent
  JSON error responses, no stack traces leaked.
- Seed data (`python -m app.core.seed`): EVERYTICKET application,
  Basic/Professional/Enterprise plans, plan transitions, a small dynamic
  registration form.

**Testing**
- `backend/tests/` - pytest suite (SQLite in-memory, spec section 73: no
  external services required) covering: full new-subscription ->
  mock-payment-SUCCESS -> ACTIVE -> invoice flow; duplicate/replayed
  SUCCESS callback idempotency (spec section 28); FAILED payment leaves
  subscription in PAYMENT_FAILED, not ACTIVE (section 20); the one-active-
  subscription rule rejecting a second subscribe attempt (409,
  `CUSTOMER_ALREADY_SUBSCRIBED`); health/ready endpoints. **All 5 tests
  pass.**
- Additionally smoke-tested by hand against a real local Postgres 16
  instance with the app actually running under uvicorn (not just the
  pytest suite): migrations applied, seed data loaded, full HTTP flow
  exercised via curl including the duplicate-callback and duplicate-
  subscribe-while-active cases, and the results verified directly in
  `psql`. Everything above matches what the automated tests assert.

## Explicitly NOT implemented yet

These are real gaps against the full spec, not hidden shortcuts - each is
called out in the relevant module's docstring too:

- **Duplicate customer detection / OTP verification** (sections 9-11):
  only the safe "exact email+mobile match -> reuse" and "no match ->
  create new" cases exist. Partial-match handling, OTP-gated identity
  reveal, and SAME/HIGHER/LOWER/EXPIRED plan routing are not built.
- **Upgrade / downgrade / cancellation / renewal / expiry** (sections
  38-43): DB support exists (plan_transitions table, subscription status
  enum, cancelled_at/by/reason columns) but no service/API layer yet.
- **Admin portal & auth** (sections 12, 51-53): AdminUser/Role/Permission
  tables exist; no login endpoint, JWT issuance, MFA, or any admin CRUD
  API yet.
- **Customer portal** (section 46), **SSO** (section 47), **direct OTP
  customer access** (section 48): tables exist (sso_sessions,
  otp_sessions); no service/API layer yet.
- **PayU gateway adapter** (section 25): interface + mock adapter are
  ready to receive it; PayU-specific code not written.
- **Everyticket integration adapter + outbound webhooks** (sections
  30-37): webhook_events/webhook_deliveries tables exist; nothing
  dispatches to them yet - `PaymentService` has an explicit comment
  marking where `subscription.activated` should be queued.
- **Email notifications** (sections 49-50): notification_templates/
  notification_logs tables exist; no EmailService/SMTP sending yet.
- **Invoices**: row + line item generation works; no PDF rendering,
  download, or email delivery yet. Tax is always 0 (no GST rate config).
- **Background jobs** (Celery/Redis, section 59): `celery_app.py` exists
  with an empty task list; no actual tasks (webhook retry, expiry
  processing, renewal, reminders) implemented.
- **Testing/simulation admin module** (section 54): the mock payment
  simulator exists as a plain API endpoint
  (`POST /api/v1/payment/mock/callback`); it is not yet behind admin
  auth or exposed as the dedicated admin Testing module the spec
  describes, and the webhook/email/SSO/test-data-generator simulators
  don't exist yet.
- **Angular frontend** (section 77): not scaffolded. `frontend/` has a
  placeholder Dockerfile/`index.html` only, so `docker compose build`
  doesn't fail on a missing context.
- **Audit logging**: the `record()` helper and table exist and are used
  for payment success/failure; not yet wired into every action the spec
  lists (plan changes, config changes, bypass usage, etc.).

## Local setup (what's runnable today)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Point at a local Postgres (docker compose up postgres, or your own):
export DATABASE_URL="postgresql+psycopg2://subscription:subscription@localhost:5432/subscription"
export ENVIRONMENT=development

alembic upgrade head
python -m app.core.seed
uvicorn app.main:app --reload

# In another shell:
curl http://localhost:8000/api/v1/public/plans
```

Run the automated tests (no Postgres needed - uses in-memory SQLite):

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

Full Docker Compose (`docker compose up`) is written and matches the
services the spec asks for, but has not been exercised in this pass since
the local execution environment used to build this had no Docker daemon
available - only a locally-installed Postgres. Before relying on it,
run `docker compose up --build` once and confirm the backend container
boots the same way the bare-metal run above did.

## Suggested next-session order

Follows spec section 91's implementation order, picking up where this
pass left off:

1. Admin auth (JWT + password + MFA with dev/staging bypass) - almost
   everything else in the admin surface depends on it.
2. Duplicate customer detection + OTP (sections 9-11) - this changes the
   `/subscribe` flow's contract, so doing it before building more on top
   of the current simplified version avoids rework.
3. Upgrade/downgrade/cancel/renew/expire service layer + API.
4. Everyticket integration adapter + outbound webhook dispatch/retry
   (Celery task), wired into `PaymentService`'s existing "NOTE" comment.
5. Email service + templates, wired the same way.
6. PayU adapter (register alongside Mock in the gateway registry -
   no core changes needed).
7. Admin portal API surface + Testing/simulation module.
8. Angular frontend, starting with the public subscribe flow (thinnest
   slice that exercises the most backend surface).
