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
  external services required). **All 18 tests pass** as of the
  2026-08-27 increment 2 below (`tests/test_end_to_end.py`,
  `tests/test_otp_and_duplicate_detection.py`,
  `tests/test_subscription_lifecycle.py`). `tests/conftest.py` sets
  TEST_MODE / ALLOW_OTP_BYPASS / ALLOW_ADMIN_MFA_BYPASS / JWT_SECRET
  itself (via `os.environ.setdefault`, before any app module is
  imported) so the suite is self-contained and doesn't depend on
  whoever invokes `pytest` having exported them.
- Additionally smoke-tested by hand, twice, against a real local
  Postgres 16 instance with the app actually running under uvicorn (not
  just the pytest suite): first pass covered the flows above (migrations
  applied, seed data loaded, duplicate-callback and duplicate-subscribe-
  while-active cases via curl, verified in `psql`); the increment 2 pass
  (below) covered admin login -> MFA(BYPASS) -> `/admin/me`, and the full
  customer flow with a **real** (non-BYPASS) OTP code end to end:
  subscribe -> payment SUCCESS -> `/identify` (exact match, real OTP
  surfaced because TEST_MODE) -> `/otp/verify` with that real code ->
  customer token -> `/customer/me` -> upgrade (BASIC -> PROFESSIONAL,
  payment SUCCESS, plan swapped) -> renew (expiry extended correctly from
  the later of now/current expiry) -> cancel (subscription CANCELLED,
  no longer the active one). Zero errors in the uvicorn log across
  either pass.

## Framework correction (2026-08-27)

The original master prompt (section 4) specified Angular for the
frontend. Vishal corrected this to **React** after the first build
session. Nothing frontend-specific had been built yet at that point, so
this is a documentation/placeholder change only (`frontend/Dockerfile`,
`frontend/package.json`, `frontend/src/index.html`, this file, and
`README.md`) - no Angular code exists anywhere in the repo to remove. All
future frontend work should target React (Vite or Create React App,
TypeScript recommended, matching the spec's "typed models, reusable
components, services, guards, interceptors" requirements from section
77). The backend is framework-agnostic on this choice - no backend code
changes were needed.

## Windows / Python 3.14 install fix (2026-08-27)

Vishal's machine runs Python 3.14.7. Several pins in `requirements.txt`
predated Python 3.14's release and had no prebuilt Windows wheel for it,
so `pip install` tried to compile them from source and failed (missing
`pg_config`, then missing the MSVC linker) rather than actually being a
code problem. Fixed by bumping every affected package to a current
release with real cp314 Windows wheels (verified on PyPI, not assumed):
`psycopg2-binary` 2.9.9 -> 2.9.12, `pydantic` 2.9.2 -> 2.13.4,
`pydantic-settings` 2.5.2 -> 2.15.0, `uvicorn` 0.30.6 -> 0.52.4,
`SQLAlchemy` 2.0.35 -> 2.0.52, `reportlab` 4.2.2 -> 5.0.1 (now pure
Python, sidesteps the question entirely).

Separately, `passlib[bcrypt]` was removed as a dependency entirely -
`app/core/security.py` now calls `bcrypt` directly. This isn't just a
version-compatibility fix: passlib 1.7.4 (unmaintained since 2020) is
fundamentally broken against any `bcrypt>=4.1`, which is what forced the
`bcrypt==4.0.1` downgrade pin during increment 2's testing. That pin was
itself fragile - an old release with no guarantee of future-Python wheel
support - so it would have kept breaking on the next Python bump too.
`bcrypt` ships an `abi3` (stable ABI) wheel, meaning one build covers
Python 3.8 through 3.14+, so calling it directly is the actually durable
fix, not a patch. Re-verified after the swap: full pytest suite (18/18)
and a real-Postgres smoke test including a genuine TOTP code (not just
`"BYPASS"`) both pass.

## Increment 2 (2026-08-27): admin auth, OTP/duplicate detection, subscription lifecycle

Built per Vishal's "continue building what was asked in the initial
prompt" instruction. Everything below is implemented, migrated against
real Postgres, unit-tested, and hand-verified via curl against the same
real Postgres instance (see Testing section above for the exact flow).

**Admin authentication (spec section 12)**
- `app/auth/service.py` - two-step login: password -> short-lived
  (5 min) `pre_mfa_token` (JWT, `type=pre_mfa`) -> MFA code ->
  access/refresh token pair (`token_kind=admin`).
- MFA is real TOTP (`pyotp`, `valid_window=1`) with a literal `"BYPASS"`
  code path, gated by `ALLOW_ADMIN_MFA_BYPASS` AND non-production,
  checked at the point of use (not just trusted from config) and
  audit-logged every time it's used.
- `POST /api/v1/admin/auth/login`, `POST /api/v1/admin/auth/mfa/verify`,
  `GET /api/v1/admin/me` (protected via `get_current_admin`).
- Dev admin seeded by `python -m app.core.seed`
  (`admin@example.com` / `ChangeMe123!`, MFA enabled, TOTP secret + a
  scannable provisioning URI printed to stdout) - documented in that
  module as dev-only, never for production.

**Duplicate customer detection + OTP (spec sections 9-11)**
- `POST /api/v1/public/identify` - given email+mobile, returns
  `match_status` of `none` (no account), `exact` (existing account,
  issues an OTP session), or `conflict` (email matches one customer,
  mobile matches a different one - refused, 409).
- `POST /api/v1/public/otp/verify` - real 6-digit OTP (bcrypt-hashed at
  rest, never stored plaintext), attempt-count rate limiting, expiry, and
  the same `"BYPASS"` pattern as admin MFA (gated the same way,
  audit-logged). Success issues a customer JWT (`token_kind=customer`).
- The plaintext OTP is only ever returned in the API response (as
  `debug_otp_code`) when `settings.TEST_MODE` is true, itself forced
  off in production by `Settings.enforce_test_mode_restrictions()` - a
  deliberate stand-in for a real SMS/email channel, which does not exist
  yet (see "not implemented" below).
- `POST /api/v1/public/plans/{code}/subscribe` was tightened to match
  spec section 9: an unauthenticated caller whose email+mobile match an
  existing account is now refused (403 `OTP_VERIFICATION_REQUIRED`)
  rather than silently reusing that account, forcing them through
  `/identify` + `/otp/verify` first. A caller presenting a valid
  customer bearer token skips identify/OTP entirely (already proven who
  they are). This is a deliberate, self-initiated correctness fix beyond
  what was originally asked for in the first pass - the original
  behavior technically violated section 9's "OTP-gate existing-account
  access" rule.

**Subscription lifecycle: upgrade / downgrade / renew / cancel (spec
sections 16, 38-43)**
- `app/subscriptions/service.py`: `assert_transition_allowed()` (checks
  the `plan_transitions` allow-list), `apply_plan_change()` (immediate
  plan swap + fresh billing period on payment SUCCESS, no proration - the
  new plan was already paid for in full), `renew_subscription()`
  (extends `expires_at` from the later of now/current expiry, so
  renewing early never loses paid-for time), `expire_subscription()`
  (ready, not yet scheduled by any Celery task - see gaps below),
  `cancel_subscription()` (immediate, no refund).
- `payment_transactions` gained a `target_plan_id` column (Alembic
  migration `1f06a0f4b4a6`, hand-edited from the autogenerated version to
  backfill existing rows before adding the NOT NULL constraint, since the
  column has no natural default) - the plan a payment is *for*, which
  differs from `subscription.plan_id` for UPGRADE/DOWNGRADE until the
  payment succeeds. `PaymentService.process_gateway_result()` now
  dispatches to the right subscription-service call based on
  `payment_type` (NEW/RENEWAL/UPGRADE/DOWNGRADE).
- `POST /api/v1/customer/subscriptions/{id}/upgrade`,
  `.../downgrade`, `.../renew`, `.../cancel`, plus
  `GET /api/v1/customer/me` (full portal: active subscription, all
  subscriptions, payments, invoices). Ownership is enforced by filtering
  on `subscription_id` AND the caller's `customer_id` - a subscription
  that isn't the caller's returns 404, not 403, so as not to leak
  whether it exists.

**Two bugs found and fixed while verifying this increment**
- `passlib==1.7.4` (last release, unmaintained) does an internal
  self-test on first use that assumes `bcrypt` still silently truncates
  secrets over 72 bytes; `bcrypt>=4.1` removed that silent truncation and
  raises `ValueError` instead, which broke every password/OTP hash
  operation. Fixed by pinning `bcrypt==4.0.1` in `requirements.txt`
  (documented inline with links to the upstream issues).
- `DateTime(timezone=True)` columns round-trip correctly on PostgreSQL
  but SQLite (used only by the pytest suite) hands back a naive
  datetime regardless of what was stored, so comparing it against
  `datetime.now(timezone.utc)` raised `TypeError: can't compare
  offset-naive and offset-aware datetimes` in OTP expiry checks and
  subscription renewal. Fixed with a new `app/core/time.ensure_aware()`
  helper (no-op on Postgres, normalizes on SQLite) used everywhere a
  DB-sourced datetime is compared against "now".

## Increment 3 (2026-08-27): React frontend + Windows local-run fixes

Built per Vishal's "how about frontend" follow-up, after he got the
backend running natively on his own Windows machine (Python 3.14.7) and
confirmed Swagger docs were reachable. Two distinct pieces of work below:
getting the *existing* backend actually running on real Windows hardware
(nothing to do with the frontend, but it's what came first this session),
then building the frontend itself.

**Windows local-run fixes (found only by Vishal actually running the
commands on his machine - none of this reproduces in the Linux build
environment used for increments 1-2)**
- `backend/.env` (Vishal's own file, not `.env.example`) had
  `DATABASE_URL`/`REDIS_URL` pointed at hostnames `postgres`/`redis` -
  those only resolve inside the `docker-compose` network, not for a
  bare-metal `uvicorn` run. Fixed to `localhost`; `.env.example` gained
  an inline comment explaining the distinction so the next person
  doesn't hit the same `could not translate host name` error.
- Postgres `password authentication failed for user "subscription"`
  turned out not to be a credentials problem at all: an unrelated,
  pre-existing container (`edps-postgres`, from a different project) was
  already bound to host port 5432, while the intended `subscription-db`
  container had no host port published. Root-caused via `docker ps -a`
  plus a direct `docker exec ... psql` test (which succeeded, proving
  the credentials were fine all along). Fixed by remapping
  `subscription-db` to host port 5433 (`backend/.env`'s `DATABASE_URL`
  updated to match) and adding a named volume
  (`subscription_pgdata:/var/lib/postgresql/data`) so a future
  `docker rm`/recreate doesn't lose data.
- Result, confirmed by Vishal: backend runs end-to-end natively on
  Windows - venv, real Postgres via Docker, Alembic migrations, seed
  data, `uvicorn --reload`, Swagger UI all working.

**CORS (spec section 77's frontend needs this; nothing to do with
Windows specifically - found while setting up the frontend dev server,
before Vishal even hit it)**
- The backend had no CORS configuration at all. Any browser-based
  frontend running on a different origin (Vite dev server on :5173 vs.
  the API on :8000) would have every request rejected before it reached
  app code. Added `CORSMiddleware` in `app/main.py` plus a new
  `CORS_ORIGINS` setting (comma-separated origin allow-list,
  `allow_credentials=False` since auth is a Bearer token, never a
  cookie). Root `.env.example` documents both the `npm run dev` origin
  (`http://localhost:5173`) and the `docker compose` frontend origin
  (`http://localhost:3000`), including both `localhost` and `127.0.0.1`
  spellings since browsers treat them as different origins.

**React frontend (spec section 77, corrected from Angular to React - see
"Framework correction" above)**
- Real React 19 + TypeScript + Vite app in `frontend/`, replacing the
  placeholder Dockerfile/`index.html`/`package.json` from the framework
  correction. See `frontend/README.md` for what it covers and how to run
  it; summary: public plan list -> subscribe (with OTP-gated
  duplicate-detection built into the same flow) -> mock payment ->
  customer OTP login -> customer portal (upgrade/downgrade/renew/cancel,
  each gated behind a mock-payment simulate step) -> admin login
  (password + TOTP/BYPASS MFA) -> a minimal admin dashboard.
- Deliberately NOT built yet: any admin CRUD UI (there's no admin CRUD
  API to call - see "Explicitly NOT implemented" below), and the dynamic
  registration-form renderer from spec section 8 (`registration_data` is
  sent as `{}` on subscribe for now).
- Verification: `npm run build` compiles clean (strict TS config from
  the Vite template - `verbatimModuleSyntax`, `noUnusedLocals`, etc.),
  and a real end-to-end Playwright browser test was run against the
  actual backend (real Postgres, not mocked) covering every flow listed
  above - plans -> subscribe -> payment -> OTP login -> portal ->
  upgrade -> renew -> cancel -> admin login+MFA -> admin dashboard - with
  zero browser console errors.
- `docker-compose.yml`'s `frontend:` service and `frontend/Dockerfile`
  were still the Phase-1 placeholders (`npm start`, which doesn't exist
  in `package.json`'s scripts; wrong env var name `API_URL` instead of
  `VITE_API_BASE_URL`) - fixed to actually build and run the real app.
  **This path (`docker compose up`) has not been verified** - no Docker
  daemon is available in the environment this was built in, only
  Vishal's own Windows Docker Desktop. The bare-metal `npm run dev` path
  above is the one that's actually been exercised end-to-end; before
  relying on `docker compose up` for the frontend, run it once and
  confirm the container serves the app the same way.

## Explicitly NOT implemented yet

These are real gaps against the full spec, not hidden shortcuts - each is
called out in the relevant module's docstring too:

- **Duplicate customer detection / OTP verification** (sections 9-11):
  **done as of increment 2** (see above) for the core exact/conflict/none
  match cases and OTP-gated identity reveal. Still missing: real
  SMS/email OTP delivery (plaintext code is only ever returned in the API
  response, and only in TEST_MODE - see increment 2 notes), OTP resend
  with cooldown enforcement (the `OTP_RESEND_COOLDOWN_SECONDS` setting
  exists but nothing reads it yet), and SAME/HIGHER/LOWER/EXPIRED plan
  auto-routing on `/subscribe` for an existing active subscriber (today
  that path still just refuses with `CUSTOMER_ALREADY_SUBSCRIBED` -
  upgrade/downgrade/renew have to be called explicitly via the customer
  portal endpoints instead).
- **Upgrade / downgrade / cancellation / renewal** (sections 38-43):
  **done as of increment 2** (see above) as customer-portal endpoints.
  **Expiry** (subscriptions past `expires_at` auto-transitioning to
  EXPIRED) still has no scheduler - `expire_subscription()` exists and is
  ready to be called, nothing calls it yet (needs the Celery beat task
  under "Background jobs" below).
- **Admin portal & auth** (sections 12, 51-53): **login/MFA/`/me` done as
  of increment 2** (see above). Still missing: any admin CRUD API
  (plans, forms, customers, subscriptions, payments, invoices, webhook
  logs, audit logs) beyond the login flow itself, and role/permission
  enforcement beyond "is this token a valid admin token" (Role/Permission
  tables exist and are seeded with a SUPERADMIN role, but no endpoint
  checks a specific permission yet).
- **Customer portal** (section 46): **`GET /customer/me` done as of
  increment 2** (active subscription, all subscriptions, payments,
  invoices). **SSO** (section 47) and **direct OTP customer access**
  (section 48, i.e. logging in via OTP alone without first going through
  `/subscribe`): tables exist (sso_sessions, otp_sessions); no
  service/API layer yet - the OTP flow built in increment 2 is scoped to
  the duplicate-detection use case inside `/subscribe`, not a standalone
  customer login.
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
- **React frontend** (section 77 of the original spec said Angular; corrected to React by Vishal on 2026-08-27 - see "Framework correction" note below): **built as of increment 3** (see above) - public plan/subscribe flow, customer OTP login + portal, admin login/MFA + minimal dashboard, all verified against the real backend with Playwright. Still missing: any admin CRUD UI (no admin CRUD API exists yet to call), and the dynamic registration-form renderer (section 8).
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

Frontend (needs the backend above running first, and its `CORS_ORIGINS`
to include whatever origin you open the frontend at - see `.env.example`):

```bash
cd frontend
npm install
cp .env.example .env   # adjust VITE_API_BASE_URL if the backend isn't on :8000
npm run dev
# open the URL Vite prints (http://localhost:5173 by default)
```

See `frontend/README.md` for what's covered and the CORS note in more
detail. `docker compose up`'s frontend service is written and fixed to
actually run the app, but - like the backend's Compose path above - has
not been exercised against a real Docker daemon in this build pass;
confirm it with `docker compose up --build` before relying on it.

## Suggested next-session order

Follows spec section 91's implementation order. Items 1-3 (below,
struck through) were completed in increment 2 (2026-08-27, see above).
Item 8 (React frontend) was pulled forward and completed in increment 3
(2026-08-27, see above) at Vishal's explicit request, ahead of items 4-7 -
those are still open and are the actual next step:

1. ~~Admin auth (JWT + password + MFA with dev/staging bypass)~~ - done.
2. ~~Duplicate customer detection + OTP (sections 9-11)~~ - done.
3. ~~Upgrade/downgrade/cancel/renew service layer + API~~ - done.
   (`expire_subscription()` exists but isn't scheduled yet - folds into
   item 4's Celery work below.)
4. Everyticket integration adapter + outbound webhook dispatch/retry
   (Celery task), wired into `PaymentService`'s existing "NOTE" comment;
   same Celery worker should also schedule `expire_subscription()` for
   subscriptions past `expires_at`.
5. Email service + templates, wired the same way.
6. PayU adapter (register alongside Mock in the gateway registry -
   no core changes needed).
7. Admin portal API surface + Testing/simulation module.
8. ~~React frontend, starting with the public subscribe flow~~ - done
   (increment 3). Still not built: admin CRUD UI (blocked on item 7's
   admin CRUD API not existing yet) and the dynamic registration-form
   renderer (spec section 8).
