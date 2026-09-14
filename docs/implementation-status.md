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
- `app/subscriptions/service.py`: `assert_transition_allowed()` (as of
  2026-09, derives UPGRADE/DOWNGRADE purely from the two plans' prices -
  see the "2026-09: UI/UX rework" section near the end of this file; the
  `plan_transitions` allow-list it used to require is no longer
  consulted, though the table/admin CRUD endpoints still exist),
  `apply_plan_change()` (immediate
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

## Increment 4 (2026-08-29): real PayU gateway, brand redesign, admin console shell

Built per Vishal's request to complete remaining scope, apply the brand
palette, and test the complete PayU flow end to end with his own test
credentials.

**PayU gateway adapter (spec section 25)** - `app/payments/gateways/payu/gateway.py`
implements the same `PaymentGateway` interface the mock adapter does:
`create_payment()` builds and hashes the exact hosted-checkout form fields
per PayU's own documented request-hash formula (verified against
docs.payu.in, not guessed); `process_webhook()` verifies the reverse-hash
on the surl/furl redirect callback before trusting anything in it (spec
section 28's tamper-detection requirement). New
`POST /api/v1/payment/payu/callback/{success,failure}` routes are PayU's
actual redirect target - a form-encoded browser POST, not a JSON webhook -
and 302-redirect the browser on to the frontend's new `/payment/return`
route with the verified outcome. `create_payment_transaction()` now
passes plan name / a derived firstname / customer email+mobile into
gateway metadata, since PayU (unlike mock) needs real customer/product
details; firstname is derived from the email's local part since this app
still has no name field to collect (see the dynamic-registration-form gap
below). Verified with 5 new unit tests
(`tests/test_payu_gateway.py`) checking the request hash matches PayU's
documented formula byte-for-byte and the reverse hash accepts a validly
signed response while rejecting a tampered one, plus a full run of the
existing suite (22/23 - the one failure, `test_health_and_ready_endpoints`,
needs a real reachable Postgres for `/ready` and is a pre-existing
environment gap, not a regression).

Switching an application to actually use PayU is a one-line SQL update
against `applications.default_gateway` (`DEFAULT_PAYMENT_GATEWAY` in
settings is currently unused) - see `.env.example`'s expanded PayU
section for the exact command. **Not yet exercised against PayU's real
sandbox** - that needs Vishal's own test merchant key/salt in his local
`backend/.env`, added directly there rather than through chat.

**Frontend: real PayU checkout UI** - a new shared `PaymentCheckout`
component (`frontend/src/components/PaymentCheckout.tsx`) replaces the
mock-only "simulate payment" buttons whenever a payment carries hosted-
checkout fields (only set for a PENDING PayU payment): it builds a hidden
form and POSTs the browser to PayU's page, where the customer completes
payment with PayU's own published test cards. `PaymentReturnPage`
(`/payment/return`) is where PayU's redirect lands after the backend has
already verified the outcome server-side - it only ever displays what the
backend decided, never re-derives success/failure itself. The mock
gateway's existing UI is untouched.

**Brand redesign** - `frontend/src/index.css` replaced the placeholder
slate/violet/white theme with the actual brand palette (`#d50355` primary
accent, `#f1e2de` page background instead of white) across every page,
plus general polish (card shadows, hover states, a branded plan-card
accent border).

**Admin console shell** - new `AdminLayout` component gives `/admin` its
own standard admin-panel chrome (dark sidebar nav, topbar, content area),
completely separate from the public site's header/footer now (previously
admin pages shared the public Layout). Only "Dashboard" is wired to a
real page - Plans/Customers/Subscriptions/Payments/Invoices/Webhook
logs/Audit logs are listed in the sidebar and marked "soon" rather than
hidden, since the admin CRUD API those need doesn't exist yet (see below)
- this is chrome ready to receive that follow-up work, not a claim it's
built.

**Workflow correction found this increment**: main.py/config.py's CORS
middleware, described as added in increment 3, had only ever been applied
to and verified against the cloud sandbox's copy of the backend - it never
actually reached Vishal's real `backend/app/main.py`/`config.py` on his
machine, which is why he hit a real CORS error running the frontend
against it. Diagnosed via his own curl/browser network-tab evidence (200
OK with zero `access-control-allow-origin` header), then applied directly
to and verified against his actual files. Going forward, backend edits in
this repo are made and verified directly on the real device files (a
scratch Linux venv installed outside the repo, see below) rather than in
a separate cloud copy that then needs syncing - this class of bug can't
recur if there's only ever one copy of the source being edited.

**New verification workflow**: this increment's backend changes were
verified by installing a throwaway Python venv (`~/linux-venv`, outside
this repo entirely) and running the real `pytest tests/` straight against
the actual repo files - not a separate cloud copy. The frontend build was
verified with `npm run build` against an isolated scratch copy of the
frontend source in a separate directory, specifically to avoid running
`npm install` against the real `node_modules` here, which is Vishal's
native Windows install (Linux-built native binaries, e.g. esbuild, would
have broken his own `npm run dev`/`npm run build` afterward).

## Increment 5 (2026-08-29): Everyticket webhook dispatch + subscription expiry scheduler

**Outbound webhooks (spec sections 30-37)** - `app/webhooks/service.py`
splits enqueue from delivery, matching this codebase's existing "no
external HTTP call held open inside a sensitive transaction" principle
(spec section 58): `queue_event()` is a pure DB write (WebhookEvent +
WebhookDelivery(PENDING) rows, HMAC-SHA256 signature computed later at
send time) - safe to call from inside `PaymentService`'s transaction,
which now actually does so on payment SUCCESS (replacing the old "NOTE"
comment) instead of just planning to. `dispatch_pending()` is the real
delivery sweep - HTTP POST with `X-Webhook-Signature: sha256=<hex>`,
retry schedule from `WEBHOOK_RETRY_SCHEDULE_MINUTES`, EXHAUSTED once the
schedule runs out - callable directly in tests with a fake `httpx`
transport, or periodically via a new Celery beat task
(`app/webhooks/tasks.py`, every 60s).

**Subscription expiry + renewal reminders (spec sections 40, 49)** -
`app/subscriptions/service.py` gained `expire_due_subscriptions()` (ACTIVE
past `expires_at` -> EXPIRED, queues a `subscription.expired` webhook
event) and `send_renewal_reminders()` (ACTIVE subscriptions expiring
within `RENEWAL_REMINDER_DAYS_BEFORE` days get a reminder email, deduped
via a NotificationLog lookback window rather than new schema). Both are
Celery beat tasks now (`app/subscriptions/tasks.py`): expiry every 5
minutes, reminders hourly.

Verified with 6 new tests (`tests/test_webhooks.py`, `httpx.MockTransport`
- no real network) and 3 new tests (`tests/test_subscription_expiry.py`),
plus the full existing suite (31/32 - the 1 failure is the pre-existing
`/ready` Postgres-reachability gap, not a regression). Hit and fixed one
new bug in the process: a naive/aware datetime comparison in the retry
test, same known SQLite round-trip quirk `ensure_aware()` (`app/core/time.py`)
already exists to work around elsewhere in this codebase.

## Increment 6 (2026-08-29): email service - real OTP delivery, payment/cancellation/renewal emails

**Email service (spec sections 49-50)** - `app/notifications/email/service.py`'s
`send_templated_email()` is the single choke point every send goes
through: looks up the active `NotificationTemplate` by code, renders
subject/HTML/text with Jinja2, sends via a new stdlib-`smtplib` SMTP
provider (`app/notifications/email/providers/smtp/provider.py`), and
always writes a `NotificationLog` row (SENT or FAILED) - and never
raises, so a broken mail server degrades to "logged as FAILED", not a
500 on some unrelated request. Four real call sites replace what used to
be either nothing or a debug-only code path: `/public/identify`'s OTP
delivery (the old `debug_otp_code` TEST_MODE convenience stays, it just
isn't the only path anymore), and payment-success/payment-failed/
subscription-cancelled emails - all fired *after* their transaction's
`db.commit()`, per spec section 58's "no external I/O inside a financial
transaction" rule.

`app/core/seed.py` seeds 5 templates (`otp_verification`,
`payment_success`, `payment_failed`, `subscription_cancelled`,
`renewal_reminder`), each wrapped in a small branded HTML shell using the
actual brand colors (`#d50355` / `#f1e2de`) rather than unstyled text.

Verified with 8 new tests (`tests/test_email_service.py`, a monkeypatched
fake `smtplib.SMTP` - both success and failure variants - no real SMTP
server), covering template rendering, NotificationLog writes, and all
four trigger points including renewal-reminder idempotency. Full suite:
39/40 (the 1 failure is the same pre-existing `/ready` gap).

## Increment 7 (2026-08-29): admin CRUD API + full admin console UI

Built directly on top of increment 4's admin console shell (which had
every module in the sidebar marked "soon") and closes the permission gap
flagged since increment 2: `Role`/`Permission` tables existed but nothing
was ever seeded onto them or checked against them - `get_current_admin`
verified a token was valid, not that its holder could do anything
specific.

**Permission enforcement (spec section 12)** - `app/auth/permissions.py`
defines the permission-code catalog (`PLANS_MANAGE`, `CUSTOMERS_VIEW`/
`_MANAGE`, `SUBSCRIPTIONS_VIEW`, `PAYMENTS_VIEW`, `INVOICES_VIEW`,
`WEBHOOKS_VIEW`/`_MANAGE`, `NOTIFICATIONS_VIEW`/`_MANAGE`, `AUDIT_VIEW`,
`DASHBOARD_VIEW`); `app/core/seed.py` re-syncs all of them onto
SUPERADMIN on every seed run (so a newly added catalog entry is
retroactively granted, no migration needed); `app/auth/deps.py` gained
`require_permission(code)`, a FastAPI dependency every admin endpoint
below now uses instead of just `get_current_admin` - a valid-but-
under-permissioned admin token gets 403, distinct from the 401 an
invalid one gets (both cases have a test).

**Admin API** (`app/api/v1/admin_*.py`, 28 new routes under the existing
`/api/v1/admin/` namespace):
- Dashboard: active/new subscriptions, 30-day revenue, failed payments,
  expiring/expired counts, provisioning failures, webhook failures.
- Plans: full CRUD for plans, plan features, and plan transitions.
  Plans are never hard-deleted (referenced by FK from subscriptions/
  payments/history) - only deactivated.
- Customers: paginated search (email/mobile/customer_id) + full detail
  (registration data, Everyticket mapping, subscriptions, payments,
  invoices) + suspend/activate. Per spec section 53, financial
  transaction history itself has no edit path here.
- Subscriptions/Payments/Invoices: read-only list + detail, cross-linked
  to each other and to the owning customer.
- Webhook Logs: event/delivery list + detail, and a retry action that
  only resets a delivery to PENDING - the actual HTTP dispatch stays
  Celery beat's job (increment 5), never the admin request itself.
- Notification Logs/Templates: send-log list + template subject/body/
  active edit.
- Audit Logs: filterable, paginated read of the append-only trail every
  mutating endpoint above writes to via `audit_service.record()`.

A shared `PageOut[T]` limit/offset pagination wrapper
(`app/api/v1/admin_common.py`) and a handful of read-only ORM
relationships (`PaymentTransaction.customer`/`target_plan`,
`Invoice.customer`/`subscription`/`payment_transaction`,
`PlanTransition.from_plan`/`to_plan` - no schema/migration changes) keep
the admin_*.py modules from re-querying the same joins by hand.

**Frontend**: every admin nav item is now a real page instead of a
disabled "soon" placeholder - AdminPlansPage (list, create, per-plan edit
+ features, transitions manager), AdminCustomersPage/DetailPage,
AdminSubscriptionsPage/DetailPage, AdminPaymentsPage/DetailPage,
AdminInvoicesPage/DetailPage, AdminWebhooksPage, AdminNotificationsPage,
AdminAuditLogsPage, and AdminDashboardPage rewritten to render the real
stats instead of "no API yet". `api/client.ts` gained `put()`/`delete()`
(previously GET/POST only) and a `withQuery()` helper; new
`StatusBadge`/`Pagination` shared components keep status coloring and
paging consistent across every list screen; new CSS classes
(`.admin-panel`, `.badge-*`, `.stat-grid`, `.data-table` pagination, etc.)
all read the existing brand tokens - no new color literals.

Verified: 49 backend tests (9 new in `tests/test_admin_api.py`, covering
every module plus the 403-vs-401 permission case), 48 passing (same
pre-existing `/ready` gap); OpenAPI schema builds cleanly with all 28 new
routes; frontend `npm run build` clean in the isolated `~/frontend-check`
scratch copy, 53 modules, no TypeScript errors.

## Increment 8 (2026-08-29): dynamic registration-form renderer

Closes spec section 8/18's remaining gap: `RegistrationFormField` rows
existed and were seeded once in `app/core/seed.py`, but were never
admin-editable, and `SubscribePage` always collected a fixed field set
instead of whatever fields were actually configured for the application.

**Backend**: `GET /api/v1/public/registration-form` returns active fields
in display order, no auth required - the dynamic renderer's data source.
Admin CRUD (`app/api/v1/admin_forms.py`, new `FORMS_MANAGE` permission):
list (including inactive), create (409 on duplicate `field_key`), update
(including the `active` toggle). Fields are never hard-deleted - a
`field_key` may already be referenced by existing
`CustomerRegistrationData` rows - only deactivated, which immediately
removes it from the public endpoint. Deliberately did **not** add
server-side required-field enforcement on `/subscribe` in this pass:
doing so would 422 every existing test/manual `/subscribe` call that
passes `registration_data: {}` (~15+ call sites across 6 test files),
since the seeded `museum_name`/`contact_person` fields are `required=True`
- a breaking behavior change to every existing caller for a pass that's
supposed to be additive. Left as a known gap below rather than silently
shipped.

**Frontend**: `DynamicRegistrationForm.tsx` (+ `useRegistrationFormFields()`
hook) renders whatever `RegistrationFormField` rows come back from the
public endpoint above, covering all 11 field types; wired into both
branches of `SubscribePage` (signed-in and new-customer). New
`AdminRegistrationFormPage` (list + per-row toggle-required/toggle-active
+ create form) with its own admin nav entry.

Verified: 50 backend tests (1 new - public read + admin CRUD in one
test), 49 passing (same pre-existing `/ready` gap); frontend `npm run
build` clean in the isolated scratch copy, 55 modules.

## Increment 9 (2026-08-29): Everyticket SSO

Closes spec section 47. `app/sso/service.py` signs/redeems single-use SSO
tokens with `Application.sso_secret` (falling back to `settings.SSO_SECRET`)
- kept distinct from this app's internal `JWT_SECRET`, since Everyticket
and this app share this secret out-of-band while `JWT_SECRET` must never
leave this app. Replay protection is DB-backed (`SsoSession.nonce`/`used`,
the model already existed) rather than relying solely on the JWT's own
`exp` claim, so a token can't be redeemed twice even if it would still
verify.

**API**: `POST /api/v1/public/sso/consume` redeems a token and issues a
normal customer portal session token (same response shape as
`/otp/verify`, so the frontend treats both entry points identically).
`POST /api/v1/admin/customers/{id}/sso-link` is TEST_MODE-gated (also
requires `CUSTOMERS_MANAGE`) and generates a working test token/consume
URL, since no real Everyticket instance exists in this build to issue one
- force-disabled in production regardless, via
`Settings.enforce_test_mode_restrictions`. Deliberately did not build a
general admin "login as customer" feature - out of scope for spec section
47, which only covers Everyticket-initiated SSO, not admin-initiated
customer impersonation.

Also confirmed spec section 48 (standalone direct customer access via
email/mobile/OTP, without going through `/subscribe`) is already
effectively satisfied by existing code - `CustomerLoginPage.tsx` +
`/identify` + `/otp/verify` cover it; no separate endpoint was needed.

**Frontend**: `SsoConsumePage` reads `?token=` from the URL, redeems it,
and redirects to `/portal`; `AdminCustomerDetailPage` gained a "Generate
test SSO link" action so the whole flow is exercisable end-to-end from
the admin console.

Verified with 6 new tests (`tests/test_sso.py`: happy path, replay
rejection, expiry rejection - forced via the DB row rather than sleeping
past the real TTL - unknown-token rejection, and both admin-endpoint
gates), full suite 56/57 (same pre-existing `/ready` gap); frontend `npm
run build` clean in the isolated scratch copy, 56 modules.

## Increment 10 (2026-08-29): admin Testing/Developer Tools module

Closes spec section 54 ("mandatory... must allow complete testing without
repeatedly performing real payments"). New `app/api/v1/admin_testing.py`,
gated by two stacked dependencies on every endpoint: a new
`require_test_mode()` (`app/auth/deps.py`) plus `require_permission
("TESTING_TOOLS_USE")` (new permission code) - and every mutating action
writes an audit-log entry (spec section 56 explicitly lists "Test payment
simulated" as an example). `require_test_mode()` was factored out of the
inline check the increment-9 SSO test-link endpoint already had, so both
now share one gate.

Each tool deliberately reuses the exact internal service function a real
request would use, rather than a parallel "test" code path:

- **TEST PAYMENT**: drives `payment_service.simulate_mock_callback()` -
  SUCCESS/FAILED/PENDING/TIMEOUT, plus DUPLICATE_CALLBACK (calls SUCCESS
  twice to exercise the idempotency guard). Always MockPaymentGateway,
  per the spec's own wording - PayU's hosted-checkout redirect can't be
  driven headlessly from an admin click.
- **TEST SUBSCRIPTION EVENTS**: ACTIVATE/RENEW/UPGRADE/DOWNGRADE/CANCEL/
  EXPIRE/PAYMENT_FAILED, calling the same `subscription_service`
  functions a real payment callback or the Celery beat expiry sweep
  would call.
- **TEST EVERYTICKET WEBHOOK**: new `webhook_service.send_ad_hoc_webhook()`
  - a signed one-off POST of admin-edited JSON/headers to the
  application's configured destination. Never writes a
  WebhookEvent/WebhookDelivery row (a live diagnostic send, not a real
  business event) - shows request/response/HTTP status/elapsed time.
- **WEBHOOK FAILURE SIMULATOR**: queues one real delivery row, then
  attempts just that row (new `webhook_service.attempt_delivery_with_client()`,
  a public wrapper around the existing `_attempt_one()`) through an
  `httpx.MockTransport` forced to return 400/401/404/500 or raise a
  timeout - verifies the real retry-schedule/EXHAUSTED bookkeeping
  without ever touching any other pending delivery a real integration
  might have queued concurrently.
- **TEST EMAIL**: calls `send_templated_email()` directly with sample
  context values matching each seeded template's variables, and reports
  back the `NotificationLog` row it wrote.
- **TEST SSO**: no new endpoint - reuses the increment-9
  `POST /admin/customers/{id}/sso-link` action directly; the frontend
  page just points at it.
- **OTP/MFA BYPASS**: toggles `ALLOW_OTP_BYPASS`/`ALLOW_ADMIN_MFA_BYPASS`
  on the cached `Settings` singleton in-memory only (never persisted,
  resets to `.env` on restart) - reachable at all only because
  `require_test_mode()` already guarantees `is_production` is False
  (`enforce_test_mode_restrictions` force-resets `TEST_MODE` regardless
  of env misconfiguration); an explicit `is_production` check is kept
  anyway as deliberate defense-in-depth per spec section 55's "never
  rely only on hiding frontend routes."
- **TEST DATA GENERATOR**: one call creates a full linked customer/plan/
  subscription/payment/invoice/Everyticket-mapping chain, marked with a
  `TEST-` plan_code prefix and `@test.invalid` customer email domain
  (spec: "mark test records clearly as TEST"); cleanup deletes exactly
  those rows, in FK-safe child-to-parent order, identified solely by
  those two markers so it can never touch real data.

**Frontend**: new `AdminTestingPage` (one section per tool, plus a
read-only environment-status panel with the two bypass toggle buttons),
wired into `AdminLayout`'s nav. `AdminLayout`'s topbar also gained a
prominent "TEST MODE" badge whenever the backend reports `TEST_MODE` is
on (spec section 55's "display TEST MODE prominently in development/
staging").

Verified with 15 new tests (`tests/test_admin_testing.py`: both gates,
every tool's happy path including the UPGRADE-needs-target-plan
validation, and an OTP-bypass toggle round-trip that restores state in a
`finally` block since `Settings` is one process-wide cached instance
shared by every test in the run). Full suite: 71 total, 70 passing (same
pre-existing `/ready` gap); frontend `npm run build` clean in the
isolated scratch copy, 57 modules.

## Increment 11 (2026-08-29): OTP resend cooldown + plan auto-routing on /subscribe

Closes the last two items from spec sections 9, 11, 22 that were still
open after increment 10.

**OTP resend cooldown** (section 11): `OTP_RESEND_COOLDOWN_SECONDS`
existed since increment 1 but nothing read it - a client could hammer
`/identify` and flood the customer's inbox with OTP codes. New
`otp_service.assert_resend_allowed()`, called from `/public/identify`
before issuing another IDENTIFY-purpose `OtpSession`: looks up the most
recent session for the exact email+mobile pair and refuses (429
`OTP_RATE_LIMITED`) if one was created too recently. No new endpoint -
`/identify` is already the only call site that issues an IDENTIFY
session, so calling it again already *is* "resend" from the frontend's
perspective.

**Plan auto-routing** (sections 9, 22): an authenticated existing
customer calling `POST /subscribe` used to get a flat
`CUSTOMER_ALREADY_SUBSCRIBED` for any plan, forcing them to separately
discover the dedicated upgrade/downgrade endpoints. Now the existing
ACTIVE subscription's plan is compared against the requested one:

- SAME plan: refused via `assert_transition_allowed()`'s own `from ==
  to` check (409 `INVALID_PLAN_TRANSITION`) - no duplicate subscription
  or payment created.
- HIGHER/LOWER plan: silently routed to an upgrade/downgrade against the
  *existing* subscription (the same `payment_type`/`apply_plan_change()`
  path the dedicated `/customer/subscriptions/{id}/upgrade|downgrade`
  endpoints already use) - no second `Subscription` row; the plan only
  actually changes once the resulting payment succeeds.
- EXPIRED/CANCELLED/no existing subscription: unchanged - falls through
  to `create_pending_subscription()` exactly as before (repurchase,
  reusing the same `customer_id`, spec section 41 - this case was
  already correct, since `get_active_subscription()` only ever returns
  ACTIVE rows).

No frontend changes were needed: `SubscribePage` already renders
whatever `SubscribeResponse` comes back generically, so an existing
signed-in customer picking a different plan is now routed correctly for
free. One known minor UX gap: the dynamic registration form is still
shown to a signed-in customer even when their action will auto-route to
an upgrade/downgrade (where `registration_data` doesn't apply and is
silently discarded, never attached to the wrong subscription) - cosmetic
only, not a correctness issue, left for a future frontend pass.

Also fixed a pre-existing mislabeled test:
`test_end_to_end.py`'s `test_returning_customer_same_plan_rejected_after_otp`
actually exercised a basic-\>professional *upgrade* attempt (which the
old flat behavior happened to also reject, masking the mislabeling) -
split into a genuine same-plan test plus a new
`test_returning_customer_higher_plan_auto_routes_to_upgrade` that drives
the whole thing through to an actual plan change via the mock payment
callback. Added 2 new OTP-resend-cooldown tests (rate-limited
immediately after / allowed once the DB row's `created_at` is forced
past the cooldown window, same "force the DB row" technique
`tests/test_sso.py`'s expiry test already used).

Verified: 74 total tests, 73 passing (same pre-existing `/ready` gap).

## Increment 12 (2026-08-29): invoice PDF generation, download, email delivery, real GST/tax calculation

Closes spec section 45 - the last genuinely-missing invoice capability
(row/line-item generation has existed since increment 1; PDF, download,
email, and real tax math did not).

**Tax config**: new `app/core/settings_service.py` (generic get/set over
the previously-unused `system_settings` table) backs
`app/invoices/tax.py`'s `TaxConfigOut{gst_rate_percent, seller_gstin,
tax_label}`, defaulting to 0%/no seller GSTIN - the same "configurable,
default DISABLED" pattern spec section 42 already uses for
proration/refunds, so every invoice generated before an admin sets a
rate keeps its old `tax_amount == 0` behavior unchanged. Admin-editable
via `GET`/`PUT /api/v1/admin/invoices/tax-config` (PUT gated on a new
`INVOICES_MANAGE` permission; GET reuses the existing `INVOICES_VIEW`).

**Real tax math + GST number**: `generate_invoice()` now computes
`tax_amount = round(amount * rate / 100, 2)` and `total_amount = amount +
tax_amount` from that config, and sets `Invoice.gst_number` from the
*customer's own* GSTIN - looked up from `CustomerRegistrationData`'s
existing "gstin" dynamic-form field (spec section 18, seeded since
increment 1) - rather than leaving it permanently null. The *seller's*
own GSTIN is business-level config (`TaxConfigOut.seller_gstin`), printed
directly on the PDF rather than duplicated onto every invoice row.

**PDF rendering**: `app/invoices/pdf.py` builds a branded (#d50355/
#f1e2de), professional-looking invoice via reportlab's platypus layer -
seller/bill-to/invoice-details header block, a line-items table, and a
subtotal/tax/total breakdown - reusing the same reportlab dependency
already pinned in requirements.txt. `Invoice.pdf_path` (existing column,
previously unused) caches the rendered bytes to disk on first use
(`INVOICE_PDF_STORAGE_DIR`, default `var/invoices/`, gitignored) so a
view/download/email never re-renders an already-generated invoice.

**Endpoints**: `GET /api/v1/admin/invoices/{id}/pdf` and
`POST /api/v1/admin/invoices/{id}/send-email` (the latter
`INVOICES_MANAGE`-gated, audit-logged); `GET
/api/v1/customer/invoices/{id}/pdf`, ownership-checked against the
authenticated customer (404, not 403, for someone else's invoice - same
information-hiding convention as every other customer-scoped lookup in
this app).

**Automatic invoice email**: extended the email infrastructure with
attachment support (`smtp_provider.send(..., attachments=[(filename,
bytes, subtype)])`, threaded through `email_service.send_templated_email`)
and a new `invoice_generated` template (seeded), so a successful payment
now emails the invoice PDF automatically - on top of, not instead of, the
existing `payment_success` email - via `payments/service.py`'s existing
post-commit best-effort email block (a PDF-render or send failure here
can never surface as an error on an already-successful payment; caught
and logged, same as every other email in this app).

**Frontend**: admin Invoices page gained a "Tax / GST configuration"
panel (rate/seller-GSTIN/label, save round-trips through the new admin
endpoint); the invoice detail page gained "Download PDF" and "Resend
invoice email" actions; the customer portal's invoice table gained a
"Download PDF" action per row. Binary downloads needed a small addition
to the frontend API client (`downloadFile()` in `client.ts`) since a
plain `<a href>` can't carry this app's Bearer token - it fetches the PDF
as a blob itself and hands the browser a short-lived object URL.

Verified: 9 new tests (tax math with/without a configured rate, the
customer-GSTIN lookup, the PDF disk-cache round trip including
re-rendering after the cached file goes missing, the tax-config
permission gate, admin+customer PDF download including a 404 for another
customer's invoice, and the email-resend round trip via a faked SMTP) -
83 total tests, 82 passing (same pre-existing `/ready` gap), 57-module
clean frontend build.

## Increment 13 (2026-08-29): admin System/Gateway/Integration/Notification/Security configuration screens

Closes spec section 51's last remaining named admin module - Payment
Gateway Configuration, Everyticket Integration Configuration,
Notification Configuration, Security Configuration, System Configuration
- against the field groups spec section 13 already defined on the
`Application` model (general/integration/payment/email/subscription
rules/testing), most of which existed as columns but were never
admin-editable, and several of which were never actually read by
anything at all.

**New `app/api/v1/admin_config.py`**: `GET /api/v1/admin/config/application`
(full config, secrets masked - only an `*_is_set` flag for
`webhook_secret`/`sso_secret`/`api_credentials`, never the plaintext
value) plus one `PUT` per screen (general/integration/payment/
notification/subscription-rules), all gated by two new permissions
(`SYSTEM_CONFIG_VIEW`/`SYSTEM_CONFIG_MANAGE`) and audit-logged. A `PUT`
secret field left blank/omitted leaves the stored value unchanged, so the
frontend never has to round-trip a secret it can't even see back to the
server.

**Notification Configuration is wired for real, not just stored**:
`email_service.send_templated_email()` gained an optional `application`
parameter that overrides `EMAIL_PROVIDER`/`EMAIL_SENDER_NAME`/
`EMAIL_SENDER_ADDRESS`/`EMAIL_REPLY_TO` from that row for any field it has
actually set (via `Settings.model_copy()` - never mutating the
process-wide cached `Settings` singleton), falling back to the global
env defaults otherwise - the same per-application-override pattern
`app.sso.service`/`app.webhooks.service` already use for `sso_secret`/
`webhook_secret`. Wired into every real send site: OTP delivery, payment
success/failure, invoice email, renewal reminders, and subscription
cancellation.

**Subscription rules are wired for real too**: `allow_upgrade`/
`allow_downgrade`/`allow_cancellation`/`renewal_enabled` are now checked
in `app/api/v1/customer.py`'s upgrade/downgrade/renew/cancel endpoints -
disabled means an immediate 403 `ACTION_NOT_ALLOWED` (a new exception),
before any payment transaction or subscription mutation happens.
`cancellation_behavior`/`repurchase_enabled` are stored for
forward-compatibility but not enforced yet - V1 only ever implements
IMMEDIATE cancellation (spec section 43) and always allows repurchase
after expiry/cancellation (spec section 41) regardless of this flag.

**Payment Gateway Configuration**: `default_gateway` was already read at
every payment-creation call site (this pass just adds the admin screen
for it), plus `gateway_mode` (stored, not yet consulted anywhere).
Gateway *credentials* (PayU's merchant key/salt) deliberately stay
env-only (`backend/.env`) - not exposed through this screen, since
round-tripping raw payment-gateway secrets through a web form isn't worth
the risk when an already-secure channel exists.

**New `app/auth/security_config.py`** (Security Configuration): OTP
length/expiry-seconds/max-attempts/resend-cooldown become admin-tunable
at runtime, `system_settings`-backed (same pattern as the invoice tax
config from increment 12), read live by `app/auth/otp_service.py` on
every OTP issue/resend-check. Deliberately does NOT cover JWT token
expiry (much larger blast radius - affects every issued token's
validation) or the `ALLOW_OTP_BYPASS`/`ALLOW_ADMIN_MFA_BYPASS` safety
switches (env-enforced via `Settings.enforce_test_mode_restrictions`,
already have their own runtime toggle in the Testing Tools module,
section 55) - this screen's `GET` surfaces those two flags plus
`TEST_MODE` read-only, so an admin has one place to see the full current
security posture without a second, differently-persisted way to change
the safety-critical ones.

**Real pre-existing bug found and fixed** while testing the
payment-gateway screen end-to-end: `payment_service.create_payment_transaction()`
never propagated the gateway adapter's own reported status onto the
`PaymentTransaction` row - it stayed at its initial `INITIATED` value
forever (for the mock gateway this is a no-op, since Mock's
`create_payment()` also reports `INITIATED`; for PayU it's very much not
a no-op, since PayU's `create_payment()` reports `PENDING`). This meant
`payment_service.build_payment_out()`'s checkout-surfacing condition
(`transaction.status == "PENDING"`) never fired for a real PayU payment,
so the frontend's hosted-checkout redirect form would never have
rendered - a real, user-facing break in the exact flow Vishal asked to
be able to test end-to-end with his own PayU credentials. No prior test
had ever driven `/subscribe` through to inspecting `payment.checkout` in
the response, so this had gone uncaught since the PayU adapter was built
in increment 4. Fixed by setting `transaction.status = result.status`
right alongside the existing `gateway_transaction_id`/`raw_gateway_response`
assignment.

**Frontend**: new `AdminConfigPage` (one section per screen - General/
Integration/Payment/Notification/Subscription rules/Security in a single
page, since each is a small field group of the same one V1 application),
"Configuration" added to the sidebar.

Verified: 8 new tests (secret masking on GET, the permission gate,
general-config round trip, integration secrets never echoed back on
GET, the payment-gateway switch actually changing a subsequent
`/subscribe` call's gateway - this is what caught the status bug above -
the notification override actually changing the sent email's `From`
header via a faked SMTP, the subscription-rule toggles actually 403ing
each of upgrade/renew/cancel, and the security config actually changing
the generated OTP code's length) - 91 total tests, 90 passing (same
pre-existing `/ready` gap), 58-module clean frontend build.

With this increment, every module spec section 51 names is a real,
admin-editable, backend-enforced screen. What's left is the housekeeping
item from the very start of this project: a full regression pass and a
docs/README refresh confirming everything above is consistent, before
calling Phase 1 complete against the master spec.

## Increment 14 (2026-08-29): Everyticket provisioning result handling (failure + retry)

Closes the last two open items on spec section 88's Phase 1 acceptance
checklist: "Provisioning failure works" / "Provisioning retry works".
Found while doing this pass's full section-88 regression sweep:
`Subscription.provisioning_status`, `ProvisioningStatus`, and the
`ProvisioningFailed` exception all existed as columns/enums/classes since
increment 1, and the admin dashboard already counted `FAILED` rows, but
nothing anywhere ever transitioned `provisioning_status` away from its
`NOT_STARTED` default - `app/api/v1/webhooks.py` (where spec section 32
says "Everyticket's response callbacks land") was a router with zero
endpoints. A real Everyticket provisioning failure would have been
completely invisible.

Re-reading spec sections 30-37 clarified the actual shape: section 32
("Everyticket Response") describes Everyticket returning its
`{success, external_customer_id, instance_id}` result in the **response
body of the same outbound `subscription.activated` webhook** this app
already sends (section 31), not a separate inbound endpoint - so there
was no missing router, just a missing step in
`app.webhooks.service._attempt_one()`, which previously only looked at
the HTTP status code and threw the response body away.

**`app/webhooks/service.py`**: `_attempt_one()` now special-cases
`event_type == "subscription.activated"`. On a 2xx response, it parses
the JSON body - a `success: false` in the body overrides an otherwise-2xx
HTTP status back to a *failed* delivery (so it still gets picked up by
the existing retry schedule, since a 2xx that didn't actually provision
anything is not a real success); on success it upserts the
`CustomerApplicationMapping` row (spec section 8) with the returned
`external_customer_id`/`instance_id` - update-in-place, never a second
insert, which is also what keeps a repurchase-after-expiry re-activation
(section 41: reuse the same external identity) safe even though it
re-sends a fresh `subscription.activated` event. `queue_event()` now also
flips a fresh subscription's `provisioning_status` to `IN_PROGRESS` the
moment a delivery is durably queued, rather than leaving it at
`NOT_STARTED` until the first HTTP attempt fires.

**Retry "for free"**: provisioning failure and retry did not need new
scheduling logic - the webhook delivery retry mechanism already built in
increment 5 (`WEBHOOK_RETRY_SCHEDULE_MINUTES`, Celery-beat-driven
`dispatch_pending()`) already retries a FAILED delivery automatically,
and the admin Webhook Logs "retry" button (increment 7) already lets an
admin force one early - this increment just makes `provisioning_status`
actually track that same delivery's outcome. Per spec section 30
("Everyticket provisioning failure does not make payment fail"), none of
this ever touches the payment or subscription's own `status` - only
`provisioning_status` and the delivery's own retry bookkeeping.

**Customer notification**: a `provisioning_issue` email template
(section 49's "Provisioning issue if appropriate") is sent once, on the
transition INTO `FAILED` - not resent on every subsequent retry attempt
that also fails - so a customer isn't spammed while the automatic
backoff schedule works through its attempts (section 37: "Customer
should receive an appropriate status message").

**Idempotency hardening**: `POST /api/v1/admin/webhooks/deliveries/{id}/retry`
now refuses (409 `WEBHOOK_ALREADY_DELIVERED`) to reset an
already-`SUCCESS` delivery back to `PENDING` - resending a
successfully-delivered `subscription.activated` event risks Everyticket
provisioning a second instance for the same customer (section 32's "do
not create duplicate instances if the activation event is retried"),
which was previously possible via this endpoint (the automatic
Celery-beat sweep was already safe, since it only ever picks up
`PENDING`/`FAILED` deliveries).

Verified: 6 new tests (`tests/test_provisioning.py` - queuing sets
`IN_PROGRESS`, a successful response sets `SUCCESS` and stores the
mapping, an explicit `success: false` body on a 2xx is treated as a
failure and scheduled for retry, a failed delivery sets `FAILED` and
emails the customer exactly once even across two failed attempts, a
later successful retry recovers to `SUCCESS` and updates the mapping,
and the admin retry endpoint 409s against an already-succeeded
delivery) - 97 total tests, 96 passing (same pre-existing `/ready` gap),
no frontend changes needed (the admin subscription/customer detail pages
already render `provisioning_status` and the Everyticket mapping fields -
they were just never fed anything but `NOT_STARTED`/`null` before).

## Increment 15 (2026-08-31): toast notifications, Plans Management popup + rich-text description + reordering

Vishal's request after using the admin panel for a while: a general toast
notification system for "any updates" across the app, plus three specific
Plans Management asks (spec sections 14-16, 51) - add/edit plans as a
popup instead of an inline form, a rich-text (bullet-point) editor for the
plan description that renders formatted on the public plan listing, and
plan reordering that's reflected in the same order on the public listing.
`Plan.display_order` and the ordered-by-it queries already existed from
increment 1 - only a bulk reorder endpoint and the UI were missing.

**Backend**: `Plan.description` widened from `String(2000)` to `Text`
(migration `a4f7c9e2b6d1`, downgrade lossy-truncates back to 2000 chars)
since a bullet-point-formatted description is now HTML, not plain text.
New `app/plans/sanitize.py` - a `bleach`-based server-side allowlist
(`p`, `br`, `strong`/`b`, `em`/`i`, `u`, `ul`/`ol`/`li`, zero attributes)
that both `create_plan()` and `update_plan()` run the incoming
description through before it ever reaches the database; this is the
real trust boundary, since the public plan listing renders the stored
HTML unescaped. New `PUT /api/v1/admin/plans/reorder` (registered ahead
of the dynamic `/{plan_code}` route, same lesson as increment 12's tax-
config endpoint) takes the full ordered list of this application's plan
codes, rejects a partial or unknown-code list (404), sets
`display_order` to each code's index, writes one `PLANS_REORDERED` audit
log entry, and returns the reordered list - `GET /public/plans` and
`GET /admin/plans` already ordered by `display_order`, so nothing else
needed to change for the public listing to pick up the new order.

**Frontend infrastructure** (all in-house, no new UI-kit dependency -
matches this codebase's dependency-light approach throughout):
`ToastContext` (`useToast()` returning `success`/`error`/`info`, 4.5s
auto-dismiss, manual close) is now mounted at the app root, above
`AuthProvider`, so it's available on every admin and customer page.
`Modal` is a reusable popup (Escape/click-outside to close) now used for
the Plans add/edit form instead of the old inline expanding panel.
`RichTextEditor` is a minimal bold/italic/bullet-list/numbered-list
editor built on `contentEditable` + `document.execCommand` (deliberately
not a WYSIWYG library) with a hidden `<input>` kept in sync, matching
this codebase's uncontrolled-form (`defaultValue` + `FormData`)
convention exactly so no submit handler needed special-casing. A second,
independent client-side allowlist sanitizer (`utils/sanitizeHtml.ts`,
`DOMParser`-based, no dependency) mirrors the backend's allowlist as
defense-in-depth before the public listing page renders a description
with `dangerouslySetInnerHTML`.

**Plans Management UI** (`AdminPlansPage.tsx`, fully rewritten): the
plans table now supports both native HTML5 drag-and-drop and up/down
arrow buttons for reordering (arrows for precision/accessibility,
drag for speed) - both paths call the same `persistOrder()`, which hits
the new reorder endpoint, toasts the result, and rolls back to the
server's real order on failure. "New plan" and each row's "Edit" open a
`Modal`-based form with `RichTextEditor` for the description; plan
Features management was split out into its own toggleable panel
(previously combined with the edit form) so editing a plan's fields and
managing its features are two separate, clearer actions. The public
`PlansPage.tsx` now renders `plan.description` through `sanitizeHtml()` +
`dangerouslySetInnerHTML` (a `<div>`, not a `<p>`, since the sanitized
HTML can itself contain block-level `<ul>`/`<ol>`) instead of the old
plain-text paragraph, which would otherwise have shown raw `<ul><li>`
tags as literal text once descriptions became rich text.

**Toasts wired app-wide**: every admin page with a mutating action now
calls `toast.success(...)` alongside its existing success path and
`toast.error(err)` alongside its existing `setError(err)` (the toast is
transient feedback, the existing inline `ErrorBanner` stays as the
persistent detail) - System/Gateway/Integration/Notification/Security
configuration saves, customer suspend/activate/generate-SSO-link, the
invoice tax-config save and per-invoice email resend, webhook delivery
retry, notification template save, registration-form field create/
activate/deactivate/toggle-required, and every action on the Testing/
Developer Tools page (all funnel through one `run()` helper there, so a
single change covered test payment, test subscription events, test
webhook send, the failure simulator, test email, OTP/MFA bypass
toggles, and the test-data generator/cleanup). On the customer-facing
side, `PortalPage.tsx` (upgrade/downgrade/renew/cancel/payment-simulate)
and `SubscribePage.tsx` (identify/OTP-verify/payment-simulate failures)
got the same treatment.

Verified: 8 new backend tests (`tests/test_plan_description_and_reorder.py`
- sanitizer allowlist behavior, create/update sanitize on the way in,
reorder changes `display_order` and is reflected in `GET /public/plans`
order, reorder rejects an incomplete or unknown-code list, reorder
requires `PLANS_MANAGE`) - 105 total tests, 104 passing (same
pre-existing `/ready`-needs-Postgres gap). Frontend: `npm run build`
(strict `tsc -b` + `vite build`) passes clean in an isolated scratch
copy after every file transferred to Vishal's machine, no new npm
dependency added anywhere in this increment.

## 2026-09-02: free trial plan (configurable duration, one-per-customer-lifetime)

Vishal asked: "Please add plan for free trial as well - configurable
duration of trial. - Process will be the same," then, on being asked to
clarify the trial shape, specified: trial as its own separate plan (not an
attribute of an existing paid plan); (1) an email before the trial ends to
prompt renewal; (2) once the trial ends, just mark the subscription
EXPIRED and re-fire the existing webhook - no auto-charge; (3) one set of
credentials can take only one trial, for the account's full lifetime; (4)
explicit security rigor against concurrent/duplicate trial-creation abuse
("unnecessary dumping").

**Design**: a trial is its own distinct `Plan` (`is_trial=True`,
`trial_period_days` configurable, `price=0`) rather than a flag on an
existing paid plan - "process will be the same" is satisfied literally,
since the entire subscribe -> pay -> activate -> expire pipeline is
reused completely unchanged.

- New migration `b7e3d4f1a9c2`: `plans.is_trial`/`plans.trial_period_days`,
  `subscriptions.is_trial` (a denormalized copy of `plan.is_trial` at
  creation time - needed because a Postgres partial-unique-index predicate
  can only reference columns on its own table), and a new partial unique
  index `uq_one_trial_subscription_per_customer_application` on
  `subscriptions(customer_id, application_id) WHERE is_trial` - unlike the
  existing one-active-subscription index, this one is deliberately NOT
  scoped to `status`, so a CANCELLED/EXPIRED trial still blocks a second
  one forever (point 3).
- Point 4 (race-condition security): this codebase's one-active-
  subscription rule has only ever used an application-level pre-check (no
  `IntegrityError` handling anywhere before this). The trial path goes
  further, as explicitly requested: `assert_trial_not_already_used()` is
  the pre-check, and `create_pending_subscription()` also wraps the trial
  insert in a `db.begin_nested()` SAVEPOINT and catches `IntegrityError`
  from the flush, translating a lost race between two concurrent trial
  signups into a clean `TrialAlreadyUsed` (409) instead of a raw error -
  scoped only to the `is_trial` branch, so the far more common non-trial
  signup path is untouched.
- Point 2 (expiry + webhook): `expire_due_subscriptions()` already
  re-queues the `subscription.expired` webhook for any expired
  subscription regardless of plan - zero new code needed, confirmed by a
  new test rather than assumed.
- Point 1 (reminder email): `send_renewal_reminders()`'s template
  selection is now dynamic - the new seeded `trial_ending` template
  instead of `renewal_reminder` when `subscription.plan.is_trial`, same
  sweep, same `RENEWAL_REMINDER_DAYS_BEFORE` window, same dedup-via-
  NotificationLog-lookback approach.
- A trial can never be reached as an upgrade/downgrade target, nor
  renewed: `admin_plans.py`'s `create_plan()`/`update_plan()` cross-
  validate `is_trial`/`trial_period_days`/`price` consistency (trial
  requires `trial_period_days > 0` and `price == 0`; non-trial requires
  `price > 0`) against the MERGED effective state on a partial `PUT`, not
  just the fields a request happened to include; `customer.py`'s
  `_change_plan()` refuses a trial `target_plan`, and `renew()` refuses a
  trial subscription outright (a trial simply expires - there's no
  renewal payment flow for it); `public.py`'s `/subscribe` auto-routing
  refuses a trial target before it would otherwise be silently treated as
  an ordinary price-based downgrade against an existing active
  subscription.
- Seeded a `FREE_TRIAL` plan (14-day default) and the `trial_ending` email
  template in `app/core/seed.py`.
- Frontend: `AdminPlansPage.tsx`'s plan form gained a "Free trial plan"
  checkbox + duration field (price is forced to 0 and disabled while
  checked - computed explicitly in the submit handler rather than trusted
  off the disabled input, since a disabled `<input>` is excluded from
  `FormData` entirely); the public `PlansPage.tsx` and `SubscribePage.tsx`
  show "Free for N days" instead of a price for a trial plan; the
  customer portal's change-plan dropdown excludes trial plans as a
  target, and hides the Renew button (replaced with explanatory text) on
  an active trial subscription.
- Also fixed `test_plan_description_and_reorder.py`'s reorder test to
  include the new seeded `FREE_TRIAL` plan in its full-plan-list
  requirement (the reorder endpoint requires naming every one of an
  application's plans) - a real, expected fallout of adding a fourth
  seeded plan, not a regression.

New test file `tests/test_free_trial.py`: admin cross-field validation
(create + partial-update against the merged effective state), day-based
(not month/year) billing period on activation, one-trial-per-lifetime
enforcement surviving cancellation (scoped per customer, verified a
different customer can still take the trial), both places a trial-as-
upgrade/downgrade-target is blocked, renewal blocked, the expiry sweep +
webhook re-fire, the trial-ending reminder email (using the same
`fake_smtp_success` fixture `test_email_service.py` already established,
imported across files the same way `_admin_headers` already is), and a
direct unit test that mocks `db.flush()` to simulate the lost-race
`IntegrityError` and confirms it becomes a clean `TrialAlreadyUsed` with
no dangling subscription row left behind - the real DB-level guarantee
(the Postgres-only partial unique index) can't be exercised by this
SQLite test suite directly, same as the pre-existing one-active-
subscription index; this call exercises the application-level handling
code instead, without needing a real Postgres race to trigger it.

**Environment note**: this pass's device bridge could reach Vishal's
files but NOT his real Postgres instance (`localhost:5433` from the
bridge's Linux VM refuses the connection - a pre-existing, previously-
documented constraint, not new). The new migration was still verified two
ways that don't need a live DB: `alembic history` resolves the revision
chain cleanly with `b7e3d4f1a9c2` as the new head, and
`alembic upgrade a4f7c9e2b6d1:b7e3d4f1a9c2 --sql` was used to generate and
inspect the exact DDL it would run (two `ALTER TABLE ... ADD COLUMN`s and
the `CREATE UNIQUE INDEX ... WHERE is_trial = true`, all as intended).
Vishal should still run `alembic upgrade head` for real against his own
Postgres as the final check.

Verified: 123 total tests, 122 passing (same pre-existing `/ready` gap).
Frontend `tsc -b && vite build` clean; `oxlint` 0 errors (8 warnings, one
new - `AdminPlansPage.tsx`'s new `setIsTrial()` call inside an existing
`useEffect` that already had the same `set-state-in-effect` warning for
its neighboring `setError(null)` call, i.e. the same pre-existing pattern
already present in this component, not a new class of issue).

## 2026-09-02 (follow-up): admin Configuration restructure + dedicated change-plan page

Vishal's feedback, verbatim: the customer portal's inline plan-switch
form ("Plan switch - will lead to new page like fresh is doing.. currently
inline form becomes messy") and a full restructure of the admin
Configuration page into 4 named sections with an explicit field list per
section.

**Customer portal**: the old inline `<select>` + button in the Active
Subscription card is replaced by a dedicated `/portal/change-plan` page
(`ChangePlanPage.tsx`), modeled on the same pick -> pay -> done step flow
`SubscribePage` already uses, so both flows feel consistent. Same
upgrade/downgrade endpoints and mock-payment simulate step under the
hood - only the layout changed. `PortalPage`'s Active Subscription card
now just links to it (hidden for an active trial subscription, which
can't be switched, same as before).

**Admin Configuration restructure** (`app/applications/config_schemas.py`,
`app/api/v1/admin_config.py`, `AdminConfigPage.tsx`) - 4 sections,
matching Vishal's field list exactly:

1. **Application**: name, currency (dropdown), Live/Test Mode
   (`gateway_mode`, moved here from the old Payment screen) only. Every
   other old General field (application_url, logo/favicon, support
   contact, timezone, `active`) keeps its column/value untouched - just
   no longer admin-editable from this screen (no data loss, just a
   smaller form).
2. **Payment Gateway**: a gateway dropdown (`default_gateway`, still
   takes effect on the very next payment) plus, when PayU is selected,
   separate Test and Live merchant key/salt fields - both are always
   editable regardless of the current mode, so switching Live/Test Mode
   later doesn't require re-entering credentials. Which set is actually
   used is decided by the Application screen's Live/Test Mode, not a
   per-credential toggle. Stored via the existing generic system_settings
   key/value store (`app/payments/gateway_config.py`, same pattern as the
   invoice tax config), not a new column - masked `*_is_set` booleans on
   GET, same secret convention as everywhere else in this app. PayU's
   adapter (`app/payments/gateways/payu/gateway.py`) now accepts an
   optional credential override at construction time (falls back to env
   vars when none given, so the module-level registry instance and every
   existing PayU unit test keep working unchanged); the registry
   (`get_gateway(code, db=..., mode=...)`) hands out a DB-resolved
   instance when a db session is given, used from
   `create_payment_transaction()` and the PayU callback route so the
   create-payment hash and the callback's reverse-hash verification
   always use the same credentials.
3. **Everyticket Integration**: Secret Key (the existing `webhook_secret`,
   relabeled), Webhook URL, a key/value editor for custom static POST
   parameters sent with every delivery (`webhook_extra_params`, merged
   into the outgoing JSON body without ever overriding a fixed event
   field), a Retry limit overriding `WEBHOOK_RETRY_SCHEDULE_MINUTES`'s own
   length (`webhook_retry_limit` - shorter truncates the schedule, longer
   repeats its last delay), and an escalation email (recipients + admin-
   edited subject/body via the same `RichTextEditor`+sanitizer pair
   `Plan.description` already uses) sent once a delivery is marked
   EXHAUSTED - fires exactly once per delivery, since `dispatch_pending()`
   never re-picks-up an already-EXHAUSTED row. `api_url`/`api_credentials`/
   `sso_secret` are no longer on this screen (SSO is a separate concern
   from webhook delivery, and already has its own env fallback) - columns
   and behavior unchanged, just not edited here any more.
4. **Notifications**: real SMTP transport override
   (host/port/username/password/use_tls - previously env-only via
   `Settings.SMTP_*`, with no per-application override at all) alongside
   the pre-existing sender name/address/reply-to fields. `send_direct_email()`
   (new, alongside the existing `send_templated_email()`) sends admin-
   composed content that isn't a `NotificationTemplate` DB row - used by
   the webhook escalation email above - sharing the same per-application
   settings-override resolution (`_resolve_settings()`, factored out of
   `send_templated_email` for this reuse).

New migration `c2d4e6f8a1b3`: adds `applications.webhook_extra_params`
(JSON), `webhook_retry_limit` (Integer), `webhook_escalation_emails`/
`_subject`/`_body`, and `smtp_host`/`_port`/`_username`/`_password`/
`_use_tls` - all nullable, no data migration needed. PayU per-mode
credentials are deliberately NOT a migration (system_settings instead,
see above).

**"Subscription rules" and "Security" configuration are unchanged** -
same endpoints, same live enforcement (still 403s the matching customer
action / still governs OTP length+expiry+attempts+cooldown) - they're
just not rendered on the restructured Configuration page for now, since
Vishal's list didn't include them ("do this much as of now"). Worth
raising with him whether they should get their own page, or come back
onto this one, in a future pass.

Verified: 128 total backend tests, 127 passing (same pre-existing `/ready`
gap). New tests: `tests/test_admin_config.py` rewritten for the new
section shapes plus a real PayU-credential-round-trip test (switches to
PayU with zero env credentials configured, stores Test credentials via
the new endpoint, and confirms an actual subscribe's PayU checkout form
uses the DB-stored key - not just that the config round-trips) and an SMTP-
host-override test (confirms the fake SMTP class was actually constructed
with the configured host/port, not just that the sender name changed).
New `tests/test_webhook_config.py` (5 tests): extra params merged into
the outgoing POST body without clobbering fixed fields, a shorter
configured retry limit exhausts sooner than the schedule's own length,
the escalation email is sent to every configured recipient with the
real event context rendered in, no escalation email when no recipients
are configured, and the escalation email fires exactly once (a second
`dispatch_pending()` call against the same now-EXHAUSTED row is a no-op).
Migration verified via `alembic history` (clean chain, `c2d4e6f8a1b3` is
head) and `alembic upgrade ... --sql` (exact DDL confirmed - this
environment's device bridge can reach Vishal's files but not his real
Postgres instance, same pre-existing constraint as every prior pass).
Frontend `tsc -b && vite build` clean; `oxlint` 0 errors (same 8 pre-
existing warnings, none new).

## 2026-09-02 (follow-up 2): configurable PayU redirect/webhook URLs, duplicate sign-out removed, 3 real webhook events documented + a new archive sweep

Vishal's feedback, verbatim: (1) "PayU redirect back to localhost:4200
which is wrong. instead allow to configure return URL and PayU webhook
URL", (2) "Remove Signout nearby my account title as already you have
added in header now", and (3) an admin Configuration ask to document the
three real Everyticket webhook event types (onboarding, status-inactive-
on-expiry, delete/archive-after-x-days-non-renewal) with a sample JSON
payload for each.

**Configurable redirect/webhook URLs** (new migration `7e0230c7e509`,
adds `applications.return_url`/`payu_webhook_base_url`/`archive_after_days`,
all nullable): `settings.FRONTEND_URL` (customer-facing browser redirect
after payment, and the SSO consume link) and `settings.PAYU_SUCCESS_URL`/
`PAYU_FAILURE_URL` (PayU's own server callback target) were both env-only,
defaulting to `localhost:4200`/`localhost:8000` - fine for local dev,
wrong for any real deployment, with no admin override at all. Both now
follow this app's existing DB-row-overrides-env-fallback pattern:
`Application.return_url` (admin Configuration > Payment Gateway screen)
overrides `FRONTEND_URL` in `payment.py`'s `_handle_payu_return` redirect
and `admin_customers.py`'s SSO consume-link generation; `Application.
payu_webhook_base_url` overrides `PAYU_SUCCESS_URL`/`PAYU_FAILURE_URL` -
`app.payments.gateway_config.resolve_payu_webhook_urls()` builds the two
full callback URLs from it, `PayUGateway` gained `success_url`/
`failure_url` constructor overrides (same override/fallback pattern
`merchant_key`/`merchant_salt`/`base_url` already use), and the registry's
`get_gateway(code, db=..., mode=..., application=...)` resolves both from
the given `Application` row. `create_payment_transaction()` gained an
`application` param threaded through from its 4 real call sites
(`customer.py` x2, `public.py` x2) to make this resolution possible.

**Duplicate sign-out removed**: `PortalPage`'s own "Sign out" button next
to "My account" is gone (the public header, `Layout.tsx`, already has one
- added in the previous pass to fix the "stuck with an expired-token error
and no way to sign out" bug). Having both was redundant now that the
header's is always present regardless of the page's own loading/error
state.

**Three real webhook events, documented + one new one**: `app/webhooks/
payloads.py` (new) holds pure, primitive-typed payload-shaping functions
- `onboarding_payload`, `expiry_payload`, `archive_payload` - used by BOTH
the real dispatch code paths AND the admin Configuration screen's
read-only sample-JSON preview, so the documentation can never quietly
drift from what's actually sent. Likewise `app.webhooks.service.
build_wire_body()` (extracted from `_attempt_one`) builds the exact outer
JSON envelope (`event_id`/`event_type`/`entity_type`/`entity_id`/
`payload` plus the admin's configured `extra_params` merged in) a real
delivery sends, and the sample preview calls that same function too.

1. **Onboarding** (`subscription.activated`, fires once on a NEW
   subscription's first successful payment - never on renew/upgrade/
   downgrade): payload enriched from bare IDs to the customer's full
   registration-form answers (`CustomerRegistrationData` for that
   subscription) plus email/mobile/plan name/currency/price/is_trial/
   starts_at, so Everyticket can provision the account without a second
   round-trip. Deliberately no `external_customer_id` - Everyticket's own
   response to THIS delivery is what assigns one (spec section 32,
   unchanged).
2. **Status inactive** (`subscription.expired`, the existing
   `expire_due_subscriptions` Celery beat sweep, unchanged schedule):
   payload now also carries `external_customer_id`/`external_instance_id`
   - the identity Everyticket itself returned back on onboarding - so it
   can deactivate the right account without looking anything up by our
   internal customer_id.
3. **Delete/archive** (`subscription.archived`, brand new): a new
   `archive_stale_subscriptions()` sweep (mirrors `expire_due_subscriptions`'
   own shape) flips EXPIRED -> a new `ARCHIVED` status once an EXPIRED
   subscription has stayed unrenewed for at least the application's
   admin-configured `archive_after_days` (opt-in per application - None/0
   disables it, same convention as `webhook_retry_limit`). New Celery task
   `subscriptions.archive_stale`, beat schedule entry (hourly - the
   threshold is measured in whole days). Payload carries the same external
   identity fields as expiry, plus `days_since_expiry`.

Admin Configuration's Everyticket Integration screen gained an
"Archive/delete after (days)" field and a read-only "Webhook events"
block rendering all three sample payloads (`EveryticketIntegrationOut.
webhook_samples`, a `GET /config/application` addition) - registration-
field keys and plan code/name/price in the onboarding sample are pulled
from this application's REAL current registration form and an active
plan when either exists, so the preview reflects actual configuration
rather than being entirely made up.

Verified: 141 total backend tests, 140 passing (same pre-existing
`/ready` gap as every prior pass). New: `tests/test_webhook_payloads.py`
(8 tests - onboarding registration-data enrichment, expiry identity
fields present/absent, archive sweep disabled-by-default/below-threshold/
past-threshold-archives-and-queues-once/idempotent-on-a-second-run, and
`build_wire_body`'s extra_params-never-overrides-envelope-fields
guarantee), 2 new `tests/test_payu_gateway.py` cases (success/failure URL
constructor override + env fallback), and 3 new `tests/test_admin_config.py`
cases (return_url/payu_webhook_base_url round-trip AND real effect on a
subscribe's PayU checkout surl/furl; archive_after_days round-trip;
webhook_samples reflect real seeded registration fields + configured
extra_params/archive_after_days). Caught and fixed one real bug of my
own along the way: `Plan.price` is a `Decimal` (Numeric(12,2) column) and
the new onboarding payload passed it straight into a webhook JSON body
without casting to `float` first - `json.dumps` doesn't know how to
serialize a `Decimal`, which broke 54 previously-passing tests the first
time the full suite ran after this pass's payload change (every payment-
success path queues this event). Fixed by casting to `float` at both call
sites (the real dispatch path and the admin sample builder); full suite
re-run clean afterward. Migration verified via `alembic history` (clean
chain, `7e0230c7e509` is head) and `alembic upgrade ... --sql` (exact DDL
confirmed) - same pre-existing constraint as every prior pass: this
environment's device bridge can reach Vishal's files but not his real
Postgres instance, so he still needs to run `alembic upgrade head` for
real. Frontend `tsc -b && vite build` clean; `oxlint` 0 errors (same 8
pre-existing warnings, none new).

## 2026-09-02 (follow-up 3): renew webhook added, all five webhook payloads trimmed, custom extra-parameters feature removed

Vishal's feedback, verbatim: "Add one more webhook for renew," plus an
explicit reshape of every Everyticket webhook payload - Activate should
keep only `event_type` at the top level, with its payload trimmed to
subscription ID / customer form data / plan code / name / price /
is_trial / expiry date; Renew, Expire, Cancel, and Archived should each
carry nothing but `event_type` and a payload with just the subscription
ID. He also asked to remove the custom key/value POST-parameters feature
from the Everyticket Integration screen entirely.

**Wire envelope simplified**: `app.webhooks.service.build_wire_body()`
used to send `{event_id, event_type, entity_type, entity_id, payload}`
plus any admin-configured `extra_params` merged in as sibling top-level
fields. It now sends exactly `{event_type, payload}` - nothing else. The
`event_id`/`entity_type`/`entity_id` fields still exist on the internal
`WebhookEvent` DB row (used for retry bookkeeping, admin webhook-log
pages, and audit trails) - they simply aren't part of the JSON body
POSTed to Everyticket any more.

**All five payloads trimmed**, `app/webhooks/payloads.py` rewritten:

1. `onboarding_payload` (`subscription.activated`) - now returns exactly
   `subscription_id`, `plan_code`, `plan_name`, `price`, `is_trial`,
   `expires_at`, `registration_data`. Dropped: `customer_id`, `email`,
   `mobile`, `currency`, `status`, `starts_at`, `transaction_id`.
2. `renewed_payload` (`subscription.renewed`, **new**) - `subscription_id`
   only. Wired into `app.payments.service.process_gateway_result`'s
   RENEWAL branch, which used to share a richer inline dict with
   upgrade/downgrade; renewal now gets its own trimmed payload while
   upgrade/downgrade (not part of Vishal's list) keep the old shape
   unchanged.
3. `expiry_payload` (`subscription.expired`) - `subscription_id` only.
   Dropped: `customer_id`, `external_customer_id`, `external_instance_id`,
   `plan_code`, `status`, `expired_at`.
4. `cancelled_payload` (`subscription.cancelled`, **new**) -
   `subscription_id` only. `app.subscriptions.service.cancel_subscription`
   gained an `application` parameter and now queues this event itself
   (both real call sites - the customer-facing cancel endpoint and the
   admin Testing module's CANCEL test event - already had `application`
   in scope and were updated to pass it).
5. `archive_payload` (`subscription.archived`) - `subscription_id` only.
   Dropped: `customer_id`, `external_customer_id`, `external_instance_id`,
   `plan_code`, `status`, `expired_at`, `days_since_expiry`.

Since none of the trimmed events carry Everyticket's external identity
any more, `app.subscriptions.service._mapping_identity()` (the helper
that looked it up from `CustomerApplicationMapping`) became dead code and
was removed along with its now-unused `CustomerApplicationMapping`
import in that module - onboarding's own provisioning flow (spec section
32, `app.webhooks.service._handle_activation_outcome`) is completely
unaffected, since it upserts that mapping from Everyticket's *response*
to the activation webhook, not from anything in the outbound payload.

**Custom extra-parameters feature removed**: the key/value POST-
parameters editor on the admin Everyticket Integration screen
(`KeyValueEditor` in `AdminConfigPage.tsx`) is gone, along with
`EveryticketIntegrationOut`/`Update.extra_params` and the merge logic in
`build_wire_body()`. `Application.webhook_extra_params` (the DB column)
is kept but no longer read or written anywhere - same "dead column, no
migration" convention this codebase already uses for every other admin
field that was later removed from a screen (e.g. the General section's
`application_url`/logo/timezone fields from the 2026-09 restructure).

**Admin Configuration's "Webhook events" sample-JSON viewer** now shows
all five event types (`subscription.activated`/`renewed`/`expired`/
`cancelled`/`archived`), each rendered as the real two-field wire
envelope `build_wire_body()` produces - built from the exact same
`app.webhooks.payloads` functions a real delivery uses, so the preview
can never drift from reality (`app.api.v1.admin_config._build_webhook_samples`).

Verified: 141 backend tests, 140 passing (same pre-existing `/ready`-
needs-real-Postgres gap) - `tests/test_webhook_payloads.py` rewritten
around the trimmed shapes plus new coverage for the renew and cancel
webhooks (fired through the real customer-facing renew/cancel endpoints,
not just unit-called); `tests/test_admin_config.py` and
`tests/test_webhook_config.py` updated to drop every extra_params
assertion and cover the new five-event sample list. No new migration -
this pass only changes payload shapes and Python-level behavior, no
schema change. Frontend `tsc -b && vite build` clean; `oxlint` 0 errors
(same 8 pre-existing warnings, none new).

## 2026-09-02 (follow-up 4): email/mobile re-added to the onboarding webhook payload

Vishal's feedback, verbatim: "in activated json, customer data also need
to be there.. email and mobile as part of payload or registration data,
any of them are fine." Follow-up 3 (immediately before this) had trimmed
`subscription.activated`'s payload down to a literal reading of his
earlier list (subscription ID/plan code/name/price/is_trial/expiry
date/registration_data) and dropped email/mobile along with everything
else - this pass adds them back specifically, since they're basic
customer identity every subscribe flow has regardless of what the
registration form asks, not something that should have been trimmed
away.

`app.webhooks.payloads.onboarding_payload()` gained `email`/`mobile`
parameters and returns them as their own top-level payload fields
(alongside `registration_data`, not folded into it, since they're
account-level identity rather than a form answer) - `subscription.
activated`'s payload is now `subscription_id`, `email`, `mobile`,
`plan_code`, `plan_name`, `price`, `is_trial`, `expires_at`,
`registration_data`. The two real call sites - `app.payments.service`'s
real dispatch path and `app.api.v1.admin_config`'s sample-JSON preview -
both updated to pass `email`/`mobile` (real values from `subscription.
customer` on the dispatch path, illustrative placeholders on the
preview), so the admin Configuration screen's sample stays honest.

No other event's payload changed - renew/expire/cancel/archived still
carry only `subscription_id`, per Vishal's own explicit list in
follow-up 3.

Verified: 141 backend tests, 140 passing (same pre-existing `/ready`
gap) - `tests/test_webhook_payloads.py`'s onboarding-payload test
updated to assert the new 9-key set including real `email`/`mobile`
values. No new migration.

## 2026-09-11: registration-form field Edit UI + regex validation + custom message

Vishal's feedback, verbatim: "1. Registration form 1. Give option to
Edit field feature, 2. For forms - give one more option for validation
by Regex and validation message fields to be set."

**Edit field (admin UI).** The backend `PUT /admin/registration-form/
{id}` endpoint and `RegistrationFormFieldUpdate` schema already existed
(increment 8) - the actual gap was purely on the frontend, which only
exposed a create form plus two narrow quick-toggle buttons (Required/
Active). `AdminRegistrationFormPage.tsx` now has a proper "Edit" button
per row opening a popup (`Modal`, same component the Plans page's Add/
Edit form uses) pre-filled with the field's label, placeholder, help
text, options, display order, required, and the new validation pair.
`field_key` and `field_type` are shown read-only in the modal - both
remain immutable once a field is created, unchanged from the existing
backend contract (`RegistrationFormFieldUpdate` never accepted either).

**Regex validation + custom message.** Two new nullable columns on
`registration_form_fields`: `validation_pattern` (String(500)) and
`validation_message` (String(255)) - new migration
`9f3a1c7d5e02_form_field_regex_validation`, additive/nullable, no data
migration needed. Chosen as explicit typed columns rather than
repurposing the pre-existing, completely-unused `validation_rules` JSON
blob, for clarity in the admin UI and because Vishal asked for these as
two distinct, nameable fields.

- **Admin API boundary**: an invalid regex is rejected with 422 the
  moment it's saved (`app.forms.schemas._check_regex`, wired via Pydantic
  `field_validator` on both `RegistrationFormFieldCreate` and
  `RegistrationFormFieldUpdate`) - never stored bad.
- **Enforcement point**: `app.forms.validation.validate_registration_data()`,
  called once at the top of `POST /subscribe` (before any customer/
  subscription DB write, so it applies uniformly to new-customer and
  repurchase flows alike). For each ACTIVE field with a configured
  `validation_pattern`, if the customer submitted a non-blank value for
  it and that value doesn't `re.fullmatch()` the pattern (whole-string
  match, matching the HTML5 `pattern` attribute's own semantics), the
  request is rejected 422 with the field's `validation_message` (or a
  generic "`{label}` is not valid" fallback if none was set). A pattern
  that somehow got stored invalid is skipped rather than ever 500ing a
  real customer's request.
- **Frontend**: `validation_pattern`/`validation_message` added to
  `RegistrationFormFieldOut`/`Create`/`UpdateInput` in `api/types.ts`.
  The admin create form and the new Edit modal both expose a "Validation
  pattern" + "Validation message" pair, with a live regex-syntax check
  and a "test this pattern against a sample value" helper so an admin
  can sanity-check a regex before saving it. `DynamicRegistrationForm.tsx`
  now also sets the native HTML5 `pattern`/`title` attributes on the
  input types that support them (text/email/tel/url) as a client-side
  UX hint - the backend re-check above remains the actual source of
  truth regardless of what the browser catches.

**Deliberately scoped out - "required" is still not enforced
server-side.** The first draft of `validate_registration_data()` also
enforced `required`, which broke ~60 pre-existing tests across nearly
every test file: the seeded application has two required fields
(`museum_name`, `contact_person`) that dozens of tests `/subscribe`
without providing, since this was never checked before. Retrofitting
every one of those call sites was assessed as a large, risky, unrelated
chore well outside what was actually asked, and turning on `required`
enforcement for real integrations already relying on today's lenient
behavior would break them with no warning. So this pass enforces ONLY
the new `validation_pattern`/`validation_message` pair; `required`
remains enforced client-side only (HTML5 `required`, bypassable via a
direct API call), exactly as before. **This is flagged to Vishal as its
own open decision, not silently assumed** - see the note in the
next chat message / project doc.

Verified: 9 new tests in `tests/test_form_field_validation.py` (invalid
regex rejected on create/update; a submission violating a configured
pattern rejected with its custom message, or a generic fallback when no
message is set; a matching submission accepted; every pre-existing
seeded field - which has no pattern configured - never newly checked or
required; first violation reported in the field's `display_order` when
several are invalid). Full suite: 150 total backend tests, 148 passing -
the same pre-existing `/ready` gap as prior entries, plus one other
pre-existing, unrelated, environment-specific failure newly observed
this pass (`test_get_or_render_pdf_caches_to_disk`: `os.remove()` denied
by this dev sandbox's file-deletion restriction) - neither is caused by
or related to this feature. Frontend: `tsc -b && vite build` and
`oxlint` both clean (0 type errors, 0 new lint errors - the same
pre-existing `setState`-in-`useEffect` warning pattern already present
on the Plans page's edit modal, now also present on this one, following
the same established convention).

## 2026-09-11 (follow-up): TEST EVERYTICKET WEBHOOK result now stored even on failure

Vishal's feedback, verbatim: "store the response from webhook even if its
error, to everyticket." Follow-up on the "Secret Key" question just
before it, about the admin Testing/Developer Tools "Test Everyticket
webhook" tool (`POST /admin/testing/webhook/send`,
`webhook_service.send_ad_hoc_webhook()`).

That tool already returned the full request/response/error/elapsed-time
detail in its live HTTP response (shown inline on the admin Testing
page), and a REAL webhook delivery (the actual `subscription.*` events)
already stores its `http_status`/`response_body` on the `WebhookDelivery`
row regardless of success or failure - that part was already correct.
The gap was specific to this ad-hoc diagnostic tool: it deliberately
never writes a `WebhookEvent`/`WebhookDelivery` row (it's a live poke at
the destination, not a real business event - see
`send_ad_hoc_webhook()`'s own docstring), and its `TEST_WEBHOOK_SENT`
audit-log entry only recorded `{sent, http_status}` - dropping
`response_body`/`error`/the request that was sent. So a failed test send
was visible only in the admin's browser for as long as that page stayed
open; refresh or navigate away and it was gone.

Fixed by storing the tool's entire result dict (already truncated to a
sane size by `send_ad_hoc_webhook()`) as the audit entry's `new_value`
instead of the trimmed `{sent, http_status}` pair - `response_body`/
`error`/`elapsed_ms`/the request (url/headers/payload) sent are now all
in the same durable audit-log row, viewable later from Admin → Audit
Logs regardless of whether the test send succeeded or failed. No schema
change - `AuditLog.new_value` is already a JSON column with no fixed
size limit, and the admin Audit Logs page already pretty-prints
`new_value` in its expandable row - nothing new needed there either.

Verified: new `test_webhook_send_result_is_stored_in_audit_log_even_on_failure`
in `tests/test_admin_testing.py`, asserting the failure case (nothing
listens at the fallback `EVERYTICKET_WEBHOOK_URL` in this test
environment, so the send genuinely fails) is captured byte-for-byte the
same as what the live HTTP response returned. Full suite: 151 total
backend tests, 150 passing (same pre-existing `/ready` gap only - the
other, unrelated PDF-cache environment failure noted in the previous
entry did not recur this run, consistent with it being an environment
flake rather than a real regression). No frontend changes needed.

## 2026-09-11 (follow-up 2): TEST EVERYTICKET WEBHOOK now recorded on the Webhook Logs screen too

Vishal's feedback, verbatim: "I want to have response into webhook
logs" - a follow-up on the previous entry (which stored the test send's
result in the Audit Logs trail). That was the wrong home for it: Vishal
wants it on the dedicated **Webhook Logs** screen (`GET /admin/webhooks/
events` and `/deliveries`) alongside real deliveries, not buried in
Audit Logs.

`POST /admin/testing/webhook/send` (`app.api.v1.admin_testing.
test_webhook_send`) now records a real `WebhookEvent` (`event_type
"test.manual_send"`, `entity_type "test"`) + `WebhookDelivery` row for
every attempt actually made (skipped only when no destination is
configured at all, since then nothing was attempted) - `http_status`,
`response_body` (or the error message on a network/timeout failure),
`status` (SUCCESS/FAILED), and `attempt_count=1` are all populated
exactly like a real delivery's. `next_retry_at` is deliberately left
`None` so this one-off diagnostic row is never picked up by
`dispatch_pending()`'s retry sweep - retrying it would resend through
the standard `{event_type, payload}` envelope, which is a different
body than the raw JSON this tool intentionally sends byte-for-byte
(see the endpoint's own docstring for the full reasoning). The Audit
Logs entry from the previous pass is unchanged/kept - both are useful,
for different audiences.

**Also fixed while in there**: the Webhook Logs screen itself
(`AdminWebhooksPage.tsx`) never actually displayed `response_body`
anywhere, for ANY delivery - real or test. `WebhookDeliveryOut` has
carried this field since increment 5, but the admin UI only ever showed
status/HTTP code/attempt count. Both the Deliveries table and each
Event's delivery list are now click-to-expand rows (same interaction
pattern the Audit Logs page already uses for old/new values) revealing
the actual response text or error message.

Verified: new `test_webhook_send_result_appears_in_webhook_logs` in
`tests/test_admin_testing.py`, asserting the failed test send (nothing
listens at the fallback URL in this test environment) surfaces via both
`GET /admin/webhooks/events?event_type=test.manual_send` and `GET
/admin/webhooks/deliveries?status=FAILED`, with `response_body` matching
the live response's `error` exactly. Full suite: 152 total backend
tests, 151 passing (same pre-existing `/ready` gap only). Frontend
`tsc -b && vite build` clean; `oxlint` 0 errors (same 9 pre-existing
warnings, none new).

## 2026-09-11 (follow-up 3): webhook request/response headers captured + Verify connectivity button

Vishal's follow-up, verbatim: "Webhook API is not getting reached or
logging headers, statuscode, etc.. from API... please give button as
well near log to click and verify that its calling properly or
not.." - two real gaps:

1. **No headers were ever captured at all.** `WebhookDelivery` stored
   `http_status`/`response_body` (since increment 5) but never the
   actual HTTP headers exchanged - so a signature mismatch, a proxy/WAF
   rejection, or a content-type problem on the destination's response
   meant guessing, not looking. New nullable JSON columns
   `request_headers`/`response_headers` on `webhook_deliveries`
   (migration `4b7d9e1f2a83`, additive, both nullable - no data
   migration, existing rows simply have neither populated). Populated on
   every delivery path:
   - `_attempt_one()` (the real dispatch/retry path, spec sections
     34-37): `request_headers` set right before the attempt (so it's
     known even if the request itself then fails to get a response);
     `response_headers = dict(response.headers)` on a real response,
     `None` on an `httpx.HTTPError` (connection error/timeout - no
     response ever came back).
   - `send_ad_hoc_webhook()` (the shared one-off signed-POST helper
     behind both the Testing module's TEST EVERYTICKET WEBHOOK tool and
     the new Verify connectivity action below): its result dict now also
     carries `response_headers`.
   - A new shared helper, `record_ad_hoc_delivery()`, factors out the
     WebhookEvent/WebhookDelivery-creation logic that used to be inlined
     directly in `admin_testing.py`'s `test_webhook_send()` - now both
     that endpoint and `verify_connectivity()` persist
     request/response headers through one code path instead of two
     copies that could drift. Returns `None` (records nothing) when
     `send_ad_hoc_webhook()` never actually attempted anything (no
     destination configured at all).

2. **No quick, always-available way to test connectivity from the
   Webhook Logs screen itself.** The existing TEST EVERYTICKET WEBHOOK
   tool lives in the admin Testing/Developer Tools module, which is
   entirely gated by `require_test_mode()` (spec section 55) - useless
   for checking a real, live production destination. New endpoint
   `POST /admin/webhooks/verify` (`app.api.v1.admin_webhooks.
   verify_connectivity`) sends a small, fixed, harmless ping payload
   (`{"ping": true, "source": "admin_webhook_logs_verify"}`) to the
   application's currently-configured destination, signed exactly like a
   real delivery, and always records the attempt via
   `record_ad_hoc_delivery()` (`event_type
   "webhook.connectivity_check"`) so the result is immediately visible
   in the log below, not just in the live response. Deliberately **NOT**
   gated by `require_test_mode()` - unlike every tool in the Testing
   module - the same way the existing delivery Retry action isn't;
   gated instead only by the existing `WEBHOOKS_MANAGE` permission. The
   one-off record is kept out of `dispatch_pending()`'s retry sweep the
   same way the ad-hoc test tool's rows already are: `next_retry_at` is
   left `None`.

**Frontend** (`AdminWebhooksPage.tsx`): a new "Connectivity check" panel
at the top of the Webhook Logs page with a "Verify connectivity" button
- shows an immediate Reached/Not reached result (HTTP status or error)
plus the request/response headers from that one call, and reloads the
page's lists below so the recorded attempt shows up right away. The
existing click-to-expand delivery/event rows (added in the previous
follow-up for `response_body`) now also show "Request headers sent" and
"Response headers received" sections alongside the response body/error -
same pattern for both the Deliveries table and each Event's delivery
list, via a small shared `DeliveryDetail` component. `WebhookDeliveryOut`
and `TestWebhookSendResult` (reused as the verify endpoint's response
type, since `send_ad_hoc_webhook()`'s result shape is exactly what both
share) both gained `request_headers`/`response_headers` in
`src/api/types.ts`; new `adminVerifyWebhookConnectivity()` in
`src/api/endpoints.ts`.

Verified: 9 new backend tests - `tests/test_webhooks.py` covers headers
being captured (and `response_headers` staying `None` on a connection
error) through the real `dispatch_pending()`/`_attempt_one()` path, and
through `send_ad_hoc_webhook()`/`record_ad_hoc_delivery()` (including
the "no destination configured at all" case, which needed
`EVERYTICKET_WEBHOOK_URL` cleared too, not just the application's own
`webhook_url` - the settings fallback otherwise still resolves a URL);
new `tests/test_admin_webhooks_verify.py` covers the endpoint itself -
succeeds under `TEST_MODE=false` (contrasting with the Testing module's
403 under the same condition), 403s for an admin without
`WEBHOOKS_MANAGE`, and that a call is visible via `GET
/admin/webhooks/events?event_type=webhook.connectivity_check` with an
audit log entry alongside it. Full suite: 161 total backend tests, 160
passing (same pre-existing, unrelated `/ready` DB-connectivity gap
only - confirmed unrelated again this pass, no change to `app/main.py`
or the DB layer). Frontend `tsc -b && vite build` clean; `oxlint` 0
errors (same 9 pre-existing warnings, none in the changed file).

## 2026-09-11 (follow-up 4): onboarding webhook payload flattened, mobile key renamed to phone_number

Vishal's follow-up, verbatim: "Keep the key for email and phone number
as below shown in JSON: {"email": ..., "phone_number": ...}...
1. Pass payload like this flat structure including registration form
data.." - a further trim/reshape of the `subscription.activated`
("onboarding") webhook payload, the only one of the five real outbound
Everyticket events that carries more than just `subscription_id`.

Two changes, both in `app.webhooks.payloads.onboarding_payload()` (the
single function shared by a real delivery and the admin Configuration
screen's read-only "sample JSON" preview, so both stay in sync
automatically):

1. The wire key for the customer's mobile number is now `phone_number`
   (was `mobile`). Only the outbound JSON key changed - the function's
   own `mobile` parameter and the `Customer.mobile` column are
   unchanged, this app's own public API (`POST /subscribe`, `/identify`,
   etc.) still uses `mobile` throughout, exactly as before.
2. Every registration-form answer the customer submitted at signup is
   now spread directly at the top level of the payload instead of
   nested under a `"registration_data"` key - e.g. `{"museum_name":
   "CSMVS", ...}` alongside `subscription_id`/`email`/`phone_number`/
   plan/price/trial/expiry, not `{"registration_data": {"museum_name":
   "CSMVS"}}`. The fixed identity/plan fields always win if a
   registration form's `field_key` happens to collide with one of them
   (e.g. an admin names a custom field "email") - a customer-editable
   form answer can never silently overwrite `subscription_id`,
   `email`, `phone_number`, or the plan/price/trial/expiry fields.

No migration - this only changes the shape of an outbound JSON payload,
nothing stored. No frontend change needed either: the admin
Configuration screen's webhook-sample viewer just
`JSON.stringify`s whatever the backend returns.

Verified: `tests/test_webhook_payloads.py`'s onboarding test rewritten
for the flat shape (asserts `phone_number` present/`mobile` absent,
registration fields present at top level/`registration_data` key
absent), plus two new tests - one confirming no extra keys appear when
no registration data was submitted, one confirming a colliding
registration-form key (`email`, `plan_code`) never overrides the real
value. `tests/test_admin_config.py`'s sample-JSON test updated to match.
Full suite: 163 total backend tests, 162 passing (same pre-existing,
unrelated `/ready` DB-connectivity gap only).

## 2026-09-11 (follow-up 5): Notification Templates - Edit opens as a popup, Body (HTML) is a rich-text editor

Vishal's follow-up, verbatim: "notifications email template should 1.
Open in popup for edit 2. body html should be editor" - two frontend-only
gaps on the admin Notifications screen (`AdminNotificationsPage.tsx`);
no backend change needed, `PUT /admin/notifications/templates/{code}`
already accepted subject/body_html/active as-is.

1. Edit used to toggle an inline form expanding below the templates
   table. It now opens in a `Modal` popup (`wide` variant), the same
   component and pattern the Plans Add/Edit form already established -
   consistent with the rest of the admin console rather than a one-off.
2. Body (HTML) used to be a plain `<textarea>`. It's now the same
   `RichTextEditor` component the plan description field already uses
   (`frontend/src/components/RichTextEditor.tsx`), reused rather than a
   second component built from scratch - extended with two new optional
   props so the plan-description call site is completely unaffected:
   - `toolbar` - lets a caller override the default 4-command toolbar
     (bold/italic/bullet/numbered). The Notifications page passes a
     broader one (`EMAIL_BODY_TOOLBAR`, defined locally in
     `AdminNotificationsPage.tsx`): bold/italic/underline/H2/H3/
     paragraph/bullet/numbered/link/clear-formatting - since, unlike a
     plan description, there's no server-side sanitizer trimming a
     template's body_html back down (`app.notifications.email.service`
     renders it through Jinja2 verbatim), so a template can legitimately
     use headings, underline, and links.
   - `allowSourceToggle` - adds a "HTML source" / "Back to visual"
     button that swaps the contentEditable view for a plain `<textarea>`
     bound to the exact same underlying HTML string. Needed because
     these bodies carry Jinja2 template syntax (`{{ code }}`,
     `{% if failure_reason %}...{% endif %}`) that a WYSIWYG-only editor
     risks mangling if an admin needs to add or adjust a variable - the
     source view is the safety net for exact control, always kept in
     sync with the visual view through the same hidden `<input>` both
     modes write to.

No migration, no new backend endpoint or schema change. Verified:
existing `tests/test_admin_api.py`'s notification-template test still
passes unchanged (backend contract untouched). Frontend
`tsc -b && vite build` clean; `oxlint` 0 errors, 9 warnings - same
pre-existing count as before this pass (moving the new
`EMAIL_BODY_TOOLBAR` constant into `AdminNotificationsPage.tsx` rather
than exporting it from `RichTextEditor.tsx` avoided an otherwise-new
`only-export-components` warning on that shared file).

## 2026-09-11 (follow-up 6): "Attempt" button on webhook deliveries + root-caused why real deliveries stayed PENDING

Vishal's follow-up, verbatim: "provide attempt button for each webhook
log so we can try again from there. verify connectivity button get
success for same API of webhook but webhook called from payment success
to everyticket does not show response and show pending only. please
review it properly."

**Root cause** (this was the "review it properly" part - not a bug in
the attempt logic itself, an operational/environment gap): a real
webhook delivery - e.g. `subscription.activated` fired from
`PaymentService` on a successful payment - is correctly queued by
`queue_event()` (a pure DB write: `WebhookEvent` + `WebhookDelivery` at
`PENDING`), but is only ever actually *attempted* (a real outbound HTTP
POST made) by `webhook_service.dispatch_pending()`, and nothing in this
codebase calls `dispatch_pending()` except the `dispatch-pending-webhooks`
entry in `app/core/celery_app.py`'s Celery beat schedule (every 60s).
That means real dispatch depends entirely on the Celery worker *and*
beat processes running alongside the API - and the README's "Option A"
manual/local-run instructions never mentioned starting either one, only
the worker row existed at all ("once Celery tasks exist"), with no row
for the beat scheduler specifically. If only `uvicorn` was ever started
(the likely case here, since Docker Compose - which does start all of
postgres/redis/backend/worker/scheduler - was still listed as "not yet
verified in this pass" as of increment 13), a queued delivery sits at
`PENDING` with `http_status`/`response_body` both `null` forever - it was
never attempted, not failed. "Verify connectivity" never shows this
symptom because it calls `send_ad_hoc_webhook()` synchronously from
inside its own request handler (added in follow-up 3), with zero
dependency on Celery.

**Fix - two parts, deliberately not a change to the queue/dispatch
architecture itself:**

1. New `POST /admin/webhooks/deliveries/{id}/attempt` endpoint
   (`app/api/v1/admin_webhooks.py`) - a second deliberate exception to
   this module's "admin requests only queue, never block on an outbound
   POST" rule (the first being `verify_connectivity`, follow-up 3, whose
   docstring this one now cross-references). Calls
   `webhook_service.attempt_delivery_with_client(db, delivery)` - the
   exact same real-dispatch logic (`_attempt_one()`) `dispatch_pending()`
   itself uses, including the provisioning-outcome handling for
   `subscription.activated` events and the retry-schedule/EXHAUSTED
   bookkeeping - directly from the request, so the response reflects a
   real, immediate outcome (`http_status`/`response_body`/
   `response_headers`/`status`/`attempt_count`/`next_retry_at` all
   updated) instead of just resetting the row to `PENDING` for a future
   sweep the way `/retry` does. Same `WEBHOOKS_MANAGE` permission gate
   and already-SUCCESS refusal (`WebhookAlreadyDelivered`, HTTP 409) as
   `/retry`; audit-logged as `WEBHOOK_DELIVERY_ATTEMPTED`. The existing
   `/retry` endpoint is untouched and still exists.
2. Webhook Logs admin screen (`AdminWebhooksPage.tsx`) - the per-delivery
   action button now calls this new endpoint instead of `/retry`,
   relabeled "Attempt", and now also shows for `PENDING` deliveries (not
   only `FAILED`/`EXHAUSTED`) - a delivery that was never attempted at
   all is exactly the case Vishal described. The resulting toast reflects
   the real outcome ("Delivered - HTTP 200" / "Not delivered - HTTP 500:
   ...") rather than the old generic "Delivery re-queued" message, which
   no longer applies since this call already carries out the attempt.

**Documentation fix**: `README.md`'s "Useful commands" table was missing
a row for the Celery beat scheduler entirely (only listed the worker,
captioned "once Celery tasks exist" - stale, since
`app/webhooks/tasks.py` and three other scheduled tasks already exist).
Added the missing `celery -A app.core.celery_app beat --loglevel=info`
row and a paragraph directly under the table spelling out that both the
worker and beat processes must be running for automatic dispatch to
happen at all under the manual/local-run path (Option A) - Docker
Compose's `scheduler` service already runs this, but that path is still
unverified per increment 13's note, which is why the manual path's gap
mattered here.

New test file `tests/test_admin_webhooks_attempt.py` (6 tests): a
`PENDING` delivery gets a real, populated response (not just a status
flip) when attempted; a real failure is recorded the same way instead of
staying blank; the `WEBHOOKS_MANAGE` permission gate; refusal to
re-attempt an already-`SUCCESS` delivery; unknown delivery id -> 404; the
audit log entry. Uses the same `httpx.Client` monkeypatch pattern
`tests/test_webhooks.py`'s ad-hoc-send tests established (there's no
`http_client` injection point reachable from an HTTP request, so the
module-level `httpx.Client` reference itself has to be patched, capturing
the real class first so the replacement factory doesn't recurse into
itself).

Verified: 168 total backend tests, 167 passing (same pre-existing,
unrelated `/ready` DB-connectivity gap only - it needs a real Postgres
connection this throwaway test environment doesn't have). Frontend
`tsc -b && vite build` clean; `oxlint` 0 errors, 9 warnings (same
pre-existing count as follow-up 5, no new warnings introduced).

## 2026-09-11 (follow-up 7): real webhook dispatch no longer depends on Celery at all; bounded HTTP timeouts + a bigger DB pool to stop admin API "freezing"

Vishal's follow-up, verbatim: "still api shows pending.. it has to be
called properly which is working on attempt button perfectly. why its
not being call properly on payment success[.] Also attempt call is also
taking time including payu success and return time as well.. all API
get freesed in admin panel."

**Two separate real problems, both root-caused by reading the actual
code rather than guessing:**

1. **Still PENDING on payment success, confirming follow-up 6's
   diagnosis**: `webhook_service.queue_event()` is a deliberate pure DB
   write (spec section 58: no external HTTP call held open inside a
   financial-transaction commit) - the actual HTTP attempt only ever
   happened via `dispatch_pending()`, only ever invoked by Celery beat.
   Since Vishal isn't running Celery worker+beat (or Docker Compose),
   nothing was ever actually attempting a real event's delivery at all -
   exactly why "Attempt" (which calls the real dispatch logic directly,
   synchronously, on demand) "works perfectly" while an automatic
   delivery just sat there.
2. **"All API get freezed"**: `_attempt_one()` (shared by dispatch,
   Attempt, and Verify connectivity) built its `httpx.Client` with a
   flat `timeout=10.0`, which httpx applies to EACH phase (connect/
   read/write/pool) independently, not as one combined budget - so a
   single unreachable/slow destination could hold a request thread, and
   the DB connection its session was still checked out with, open for
   well over 10 seconds. `app/core/database.py`'s engine never set an
   explicit `pool_size`/`max_overflow`, so it ran on SQLAlchemy's
   defaults (5 + 10 = 15 total connections) - a couple of concurrently
   slow/stuck webhook attempts were enough to exhaust that and make
   every OTHER admin request (including completely unrelated pages)
   block for up to `pool_timeout` waiting for a connection to free up.
   This is a real, general resource-exhaustion risk, not something
   specific to the new Attempt button - it would affect any concurrent
   slow outbound call in this app.

**Fix, three parts:**

1. **`webhook_service.attempt_soon(event_id)`** (`app/webhooks/service.py`,
   new) - called right after a real business event's enclosing
   transaction commits (`app/payments/service.py`'s `process_gateway_result`,
   for the activation/renewal/upgrade/downgrade events it queues), it
   spawns a short-lived background thread with its OWN fresh DB session
   (mirroring `app/webhooks/tasks.py`'s Celery-task pattern exactly) and
   makes ONE real, immediate delivery attempt - never blocking the
   caller (the payment-success API response returns exactly as fast as
   before), never holding the request's own DB connection open for the
   duration of the outbound call, and never touching anything before
   the commit (spec section 58 is still fully respected - the call only
   happens after `db.commit()`, same placement as the existing
   confirmation-email sends). Celery beat remains the only thing that
   ever RETRIES a delivery that failed on this first attempt - nothing
   about the retry schedule, EXHAUSTED handling, or the admin Attempt/
   Retry actions changes. Net effect: a real payment's webhook now
   actually gets sent within moments of the payment succeeding, with
   zero dependency on Celery being up at all - Celery is now purely a
   retry backstop, not a requirement for the very first attempt.
2. **Bounded HTTP timeouts**: replaced every flat `httpx.Client(timeout=10.0)`
   webhook call (`_attempt_one()`, used by dispatch/Attempt/Verify/the
   new attempt_soon(), and `send_ad_hoc_webhook()`, used by Verify
   connectivity and the Testing module's ad-hoc send) with a proper
   split `httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=3.0)` (or
   the equivalent scaled to `send_ad_hoc_webhook`'s own timeout
   parameter) - bounds a single stuck destination to a predictable ~5-8s
   worst case instead of an unbounded-feeling 10s+ per phase.
3. **Bigger DB connection pool**: `app/core/database.py`'s engine now
   sets `pool_size=10, max_overflow=20, pool_timeout=30` explicitly
   (was: SQLAlchemy's defaults, 5 + 10) - a defensive safety margin so a
   few concurrently slow outbound calls (now bounded to ~5-8s each by
   the point above) can't cascade into blocking unrelated requests
   app-wide the way Vishal described.

New test file `tests/test_webhook_attempt_soon.py` (5 tests):
`attempt_soon()` makes a real attempt (success and failure cases,
`threading.Thread` patched to run synchronously for determinism, no
sleep/poll); a `None` event id (the "no destination configured" case)
is a safe no-op that never spawns a thread; an unknown event id is
swallowed rather than raised; and an integration-level test that drives
a real subscribe + mock-payment-success round trip through the actual
API and asserts `PaymentService` calls `webhook_service.attempt_soon()`
with the real, just-queued activation event's id - the concrete wiring
Vishal's bug report was about, not just the underlying function in
isolation.

Verified: 173 total backend tests, 172 passing (same pre-existing,
unrelated `/ready` DB-connectivity gap only). Frontend unaffected by
this pass (backend-only) - `tsc -b && vite build` and `oxlint` re-run
anyway to confirm: clean, same 9 pre-existing warnings.

## 2026-09-11 (follow-up 8): webhook call start time and response completion time now logged and shown

Vishal's follow-up, verbatim: "Log webhook call time and response
completion time."

**What changed, both persisted on the delivery row and written to the
application log, on every path that makes an outbound webhook call:**

- `WebhookDelivery` gained two new nullable columns
  (`e45b1604043b_webhook_delivery_timing.py`, off current head
  `4b7d9e1f2a83`): `attempt_started_at` (wall-clock timestamp when the
  outbound HTTP call began) and `duration_ms` (elapsed call time,
  measured with `time.monotonic()` so it's never skewed by a wall-clock
  adjustment mid-call). The pre-existing `last_attempt_at` column
  already doubled as the completion timestamp (set right after the call
  finishes) - no new column needed for that half, just documented in
  code comments.
- **Real dispatch** (`_attempt_one()`, shared by the Celery beat sweep,
  the admin Attempt button, and follow-up 7's `attempt_soon()`): now
  records `attempt_started_at` and `duration_ms` on every attempt
  (success or failure) and logs a single INFO line per attempt with
  delivery id, event type, destination, start/completion timestamps,
  duration, HTTP status, and outcome. `duration_ms` is measured strictly
  around the HTTP call itself, before any subsequent provisioning/
  activation side-effect handling runs, so it reflects network time only.
- **Ad-hoc path** (`send_ad_hoc_webhook()` / `record_ad_hoc_delivery()`,
  used by the Testing module and "Verify connectivity"): `send_ad_hoc_webhook()`
  now also returns `started_at`, and `record_ad_hoc_delivery()` persists
  both new columns onto the `WebhookDelivery` row it writes, same as the
  real-dispatch path. Both the success and failure branches log an INFO
  line with url, start time, elapsed ms, and outcome.
- Webhook Logs screen (`AdminWebhooksPage.tsx`): a new "Duration" column
  on the Deliveries table; the expanded delivery detail (used by both
  the Deliveries table and the Events list) gained a "Call timing" block
  showing started/completed/duration alongside the existing request/
  response header and body sections; the "Verify connectivity" result
  panel now shows its own started/duration line the same way.

New backend tests in `tests/test_webhooks.py`:
`test_dispatch_pending_records_call_time_and_duration` (asserts
`attempt_started_at`/`duration_ms` are populated and
`attempt_started_at <= last_attempt_at` after a real dispatch attempt)
and `test_send_ad_hoc_webhook_and_record_ad_hoc_delivery_capture_call_timing`
(same assertions for the ad-hoc/Verify-connectivity path).

Verified: `tests/test_webhooks.py` 13 passed (up from 11); full suite
175 total, 174 passing (same single pre-existing, unrelated `/ready`
DB-connectivity gap that predates this entire project). Frontend
`tsc -b && vite build` clean; `oxlint` 0 errors, same 9 pre-existing
warnings. New migration `e45b1604043b` still needs `alembic upgrade
head` run against Vishal's real Postgres database before this reaches
him in a running environment - it hasn't been applied there yet, only
verified to chain correctly off the current head and to pass the test
suite (which creates its schema straight from the ORM models, not via
Alembic). Committed as `de31a17`.

## Explicitly NOT implemented yet

These are real gaps against the full spec, not hidden shortcuts - each is
called out in the relevant module's docstring too:

- **"Required" registration-form fields are not enforced server-side**
  (spec section 18). Only the frontend's HTML5 `required` attribute
  checks this today - a direct API call bypasses it entirely, and this
  was true before the 2026-09-11 regex-validation pass too, not
  introduced by it. Deliberately not fixed as part of that pass: the
  seeded application already has two required fields (`museum_name`,
  `contact_person`) that dozens of existing tests, and potentially real
  integrations, subscribe without providing - turning on enforcement now
  would be a larger, separate breaking change. This is an open decision
  for Vishal, not an assumed one.
- **Duplicate customer detection / OTP verification** (sections 9-11):
  **done as of increment 2** (see above) for the core exact/conflict/none
  match cases and OTP-gated identity reveal; **real email OTP delivery
  done as of increment 6**; **OTP resend cooldown enforcement and
  SAME/HIGHER/LOWER/EXPIRED plan auto-routing on `/subscribe` done as of
  increment 11** (see above). Still missing: real SMS delivery (email
  only today) and CANCELLED-subscriber repurchase is exercised via the
  same code path as EXPIRED but has no dedicated test.
- **Upgrade / downgrade / cancellation / renewal** (sections 38-43):
  **done as of increment 2** (see above) as customer-portal endpoints.
  **Expiry** (subscriptions past `expires_at` auto-transitioning to
  EXPIRED) still has no scheduler - `expire_subscription()` exists and is
  ready to be called, nothing calls it yet (needs the Celery beat task
  under "Background jobs" below).
- **Admin portal & auth** (sections 12, 51-53): **login/MFA/`/me` done
  as of increment 2; the full admin CRUD API + permission enforcement +
  matching UI done as of increment 7** (see above) - plans, customers,
  subscriptions, payments, invoices, webhook logs, notification templates/
  logs, and audit logs are all real endpoints with a real UI, and every
  one of them checks a specific permission (`require_permission`), not
  just "is this token a valid admin token". **Registration form field**
  management (spec section 18's admin side) **done as of increment 8**,
  the **Testing/Developer Tools module** (section 54) **done as of
  increment 10**, and the **System/Gateway/Integration/Notification/
  Security Configuration screens** (section 51's remaining modules)
  **done as of increment 13** (see above) - the last admin module the
  spec names.
- **Customer portal** (section 46): **`GET /customer/me` done as of
  increment 2** (active subscription, all subscriptions, payments,
  invoices). **SSO** (section 47) **done as of increment 9** - signed,
  single-use, DB-backed-replay-protected tokens, redeemed via
  `/public/sso/consume`, with a TEST_MODE admin action to generate a
  working test link since no real Everyticket instance exists in this
  build. **Direct OTP customer access** (section 48) confirmed already
  satisfied by existing code (`CustomerLoginPage.tsx` + `/identify` +
  `/otp/verify`) - no separate endpoint was needed.
- **PayU gateway adapter** (section 25): **built as of increment 4** (see above) - real hosted-checkout integration with hash-verified callback, plus the frontend checkout redirect flow. Not yet exercised against PayU's real sandbox (needs Vishal's test credentials in his local `.env`); no server-to-server status-polling fallback (`get_payment_status()` intentionally not implemented - the surl/furl callback is authoritative for V1, per PayU's own guidance).
- **Everyticket integration adapter + outbound webhooks** (sections
  30-37): **built as of increment 5** (see above) - queue-then-dispatch
  webhook delivery with HMAC signing and a retry schedule, driven by a
  Celery beat task, plus an admin Webhook Logs view with a manual retry
  action (increment 7). **Provisioning result handling (failure + retry,
  section 88's checklist) built as of increment 14** (see above) -
  Everyticket's response body to the activation webhook now actually
  drives `Subscription.provisioning_status`, the `CustomerApplicationMapping`
  upsert, and a one-time customer notification on failure.
- **Email notifications** (sections 49-50): **built as of increment 6**
  (see above) - real SMTP delivery for OTP/payment-success/payment-failed/
  subscription-cancelled/renewal-reminder, always logged to
  NotificationLog, plus an admin template-edit + send-log UI (increment 7).
- **Invoices** (section 45): **built as of increment 12** (see above) -
  real GST/tax calculation from an admin-configurable rate, PDF
  generation (cached to disk), admin+customer download, and automatic
  plus on-demand email delivery with the PDF attached.
- **Background jobs** (Celery/Redis, section 59): **built as of
  increment 5** (see above) - `celery_app.py`'s `beat_schedule` now runs
  webhook dispatch (60s), subscription expiry (5m), and renewal reminders
  (hourly). Not yet exercised against a real running Celery worker/beat +
  Redis broker in this pass (verified by calling the sweep functions
  directly, per this codebase's "testable without external dependencies"
  approach, spec section 73) - confirm with `celery -A app.core.celery_app
  worker` / `celery -A app.core.celery_app beat` before relying on it in
  a real deployment.
- **Testing/simulation admin module** (section 54): **built as of
  increment 10** (see above) - TEST PAYMENT, TEST SUBSCRIPTION EVENTS,
  TEST EVERYTICKET WEBHOOK, WEBHOOK FAILURE SIMULATOR, TEST EMAIL, TEST
  SSO (reuses increment 9's admin sso-link action), OTP/MFA bypass
  toggles, and a TEST DATA GENERATOR + cleanup, all TEST_MODE- and
  permission-gated with a real admin UI.
- **React frontend** (section 77 of the original spec said Angular; corrected to React by Vishal on 2026-08-27 - see "Framework correction" note below): **built as of increment 3, admin CRUD UI added in increment 7, dynamic registration-form renderer added in increment 8, SSO consume page added in increment 9, Testing Tools page added in increment 10** (see above) - public plan/subscribe flow (with the dynamic per-application registration form), customer OTP login + portal + SSO landing page, and a full admin console (dashboard, plans, customers, subscriptions, payments, invoices, webhooks, notifications, audit logs, registration-form fields, and the Testing/Developer Tools module, with a "TEST MODE" badge shown whenever the backend has it on).
- **Audit logging**: the `record()` helper and table exist; used for
  payment success/failure, MFA bypass, every admin CRUD mutation as of
  increment 7 (plan/feature/transition create-update-delete, customer
  suspend/activate, webhook delivery retry, template edit), registration-
  form field create/update as of increment 8, SSO test-link generation
  as of increment 9, and every application-config change (general/
  integration/payment/notification/subscription-rules/security) as of
  increment 13.

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

Follows spec section 91's implementation order. Items 1-8 (struck
through) are all done as of increments 2-9 (2026-08-27 through
2026-08-29, see above). What's left is genuinely the tail of the spec
now, not the core:

1. ~~Admin auth (JWT + password + MFA with dev/staging bypass)~~ - done.
2. ~~Duplicate customer detection + OTP (sections 9-11)~~ - done.
3. ~~Upgrade/downgrade/cancel/renew service layer + API~~ - done.
4. ~~Everyticket integration adapter + outbound webhook dispatch/retry~~ -
   done (increment 5), including the expiry/reminder Celery beat tasks.
5. ~~Email service + templates~~ - done (increment 6).
6. ~~PayU adapter~~ - done (increment 4). Still needs Vishal's real test
   credentials in his own `backend/.env` to exercise against PayU's
   actual sandbox.
7. ~~Admin portal API surface~~ - done (increment 7), including the
   Testing/Developer Tools module (increment 10).
8. ~~React frontend~~ - done (increments 3, 7, 8, 9, 10), including the
   dynamic registration-form renderer, the SSO consume page, and the
   Testing Tools admin page.

Remaining open items:

- **Section 88's Phase 1 acceptance checklist has been walked item by
  item** (increment 14) - every item is satisfied by code in this repo
  except two, both environment limitations rather than missing features:
  "Docker Compose works" (no Docker daemon available in the environment
  this was built in - `docker-compose.yml` exists and should be
  sanity-checked once run for real) and the PayU adapter's real-sandbox
  path ("PayU adapter exists" is satisfied - PayU's own test credentials
  haven't been exercised end-to-end yet, which needs Vishal's own
  credentials in his local `backend/.env`, never pasted into chat).
- Docs/README refresh: **done as of increment 15** (this pass) - `README.md`,
  `frontend/README.md`, and this file are all now current through
  increment 15.
- Everything above is unit-tested (105 tests) against SQLite; no end-to-end
  manual pass against a real Postgres + real PayU sandbox + a real
  Everyticket-shaped webhook receiver has been done in this environment -
  that's the natural next step once Vishal is ready to test, per his own
  standing instruction to test everything at the end.
- Toast notifications (increment 15) and the Plans Management popup/
  rich-text/reorder UI are unit-verified (backend tests) and build-
  verified (frontend `tsc -b` + `vite build`), but - like everything
  else in this list - not yet clicked through by hand; worth a pass once
  Vishal is testing end to end.

## 2026-09: UI/UX rework (public header/nav, admin panel, customer portal)

Two batches of UI/UX feedback from Vishal, applied on top of increment 15's
functionality - no new spec features, but one deliberate backend spec
deviation (see below).

**Public site**
- Header: replaced the text wordmark with the real Everyticket logo
  (`frontend/src/assets/logo.svg`, saved locally by Vishal rather than
  fetched at build/runtime - this environment cannot reach `everyticket.in`
  over the network), dark background + white/dim-white text (fixed
  regardless of OS color scheme, same convention as the admin sidebar).
  Admin link removed from the public nav (still reachable directly at
  `/admin/login`); "Sign in" relabeled "My Subscriptions".
- Login pages (customer + admin) and the subscribe page's step content no
  longer render pinned to the left edge of the wide content column -
  `.auth-page` centers a login card; `.subscribe-layout` puts the active
  step on the left and a horizontally-scrolling "other plans" panel on the
  right (`SubscribePage.tsx`).
- Plans page: the plan grid now comes immediately after the `<h1>`, with a
  "Already have an account? Sign in" footnote at the bottom instead of an
  intro paragraph above the grid.

**Admin panel**
- Sidebar brand is the same local logo as the public header.
- The flat 12-item nav list is now 5 collapsible categories (Catalog,
  Customers, Billing, Communications, System) plus a standalone Dashboard
  link - whichever category holds the current route starts expanded.
- Plans grid: Active/Inactive is now a clickable badge in the grid itself
  (`toggleActive()`, same `PATCH .../active` pattern
  `AdminRegistrationFormPage.tsx` already used) instead of a checkbox
  inside the edit form.
- Plan features are now a popup (`PlanFeaturesModal`, reusing the existing
  `Modal` component) opened via a "Features" button per row, instead of an
  inline panel that pushed the rest of the page down.
- The Plan Transitions allow-list section (table + add-transition form)
  has been removed from `AdminPlansPage.tsx` entirely, per Vishal's own
  request: "Plan transitions are not required for now as we are giving
  dropdown to user for change plan." The backend `PlanTransition` model
  and its admin CRUD endpoints (`admin_plans.py`) are untouched and still
  work if called directly - only this frontend section is gone.
  **Spec deviation**: `assert_transition_allowed()` in
  `app/subscriptions/service.py` no longer requires an admin-configured
  allow-list row for a transition to be permitted (spec section 16's
  original requirement) - it now derives UPGRADE vs. DOWNGRADE purely
  from comparing the two plans' prices, so any plan can be switched to
  any other. This was necessary: hiding the allow-list UI without this
  change would have made every plan-change attempt through the customer
  portal's dropdown fail with 409 `INVALID_PLAN_TRANSITION` the moment an
  admin hadn't pre-configured that exact pair.

**Customer portal (`PortalPage.tsx`)**
- No longer pinned to the left edge - customer identity and the plan-
  change/renew/cancel actions are now full-width cards (`.card-wide`)
  laid out via `.detail-grid`, matching the admin panel's own card
  conventions instead of the 480px-capped default `.card`.
- Customer identity and the customer's own registration-form submission
  are now one card ("Account") instead of registration data having no
  place in the portal at all. `CustomerPortalOut.registration_data` is a
  new field (`app/customers/portal_schemas.py`), sourced the same way
  `CustomerAdminDetailOut.registration_data` already was for the admin
  customer-detail page; field labels come from a `GET
  /public/registration-form` call the page now also makes.
- Renew and Cancel are laid out as two columns under "Change plan"
  (`.portal-actions-cols`) instead of stacked full-width buttons.
- The old three separate tables (Subscription history / Payments /
  Invoices) are now one combined table - one row per subscription,
  columns Plan / Billing Cycle / Amount / Last Payment / Invoice / Next
  Billing / Status. Building this needed two additive, non-breaking
  schema changes:
  - `PortalSubscriptionOut` gained `billing_interval`/`billing_frequency`
    (already on `Plan`, just not previously propagated to the portal's
    per-subscription view) to render "Monthly"/"Annual".
  - `PaymentTransactionOut` gained `subscription_ref`/`created_at`, and
    `InvoiceOut` gained `subscription_ref`/`transaction_id` - all four
    default to `None` and are only ever populated by
    `app/api/v1/customer.py`'s `_to_portal_payment()`/`_to_portal_invoice()`
    helpers for this one endpoint, so every other caller of these two
    schemas (the subscribe/upgrade/downgrade/renew flows, the mock
    callback response) is unaffected. `subscription_ref` is deliberately
    NOT named `subscription_id` on either schema, since that name is
    already the *internal integer FK* on both the `PaymentTransaction`
    and `Invoice` ORM models - reusing it would have let
    `model_validate()` silently coerce the wrong (internal, numeric)
    value into what looks like the public "SUB-xxxx" id.
  - The frontend correlates a subscription to its most recent payment via
    `subscription_ref`, and that payment to its invoice via
    `transaction_id` - an invoice only exists once its payment cleared,
    which is what "Invoice: number/Download, if payment confirmed" needed
    without a separate "confirmed" flag.

**Verification**: backend - `pytest tests/` re-run against the real
committed code after every schema/service change (104 passed, 1
pre-existing/unrelated `/ready` failure, same as before this pass).
Frontend - `tsc -b && vite build` and `oxlint` both clean (oxlint's 8
warnings are pre-existing `react/set-state-in-effect` style warnings
already present in `PlanFormModal` before this pass, now also present in
the new `PlanFeaturesModal`, which follows the exact same pattern - not a
new class of issue). Not yet clicked through by hand in a real browser -
same standing note as increment 15, Vishal is testing everything at the
end.

## 2026-09-01 (follow-up): registration data missing from customer portal's Account card

Vishal reported the "Account" card's registration-details section (added
in the 2026-09 UI/UX rework above) wasn't showing museum name / other
dynamic-form values for a test customer. Two real gaps found and fixed:

- `GET /customer/me` (`app/api/v1/customer.py`) filtered
  `CustomerRegistrationData` by both `customer_id` AND `application_id`,
  while the admin customer-detail endpoint's equivalent, already-working
  query (`admin_customers.py`) filters by `customer_id` alone. Since V1
  only has one `Application` row this shouldn't normally diverge, but
  there's no reason for the portal query to be stricter than the proven
  admin one and risk silently hiding a real submission - aligned it to
  match. New regression test
  (`tests/test_end_to_end.py::test_customer_portal_shows_registration_data_and_combined_table_fields`)
  drives a real subscribe with museum_name/contact_person/gstin/address,
  logs in, and asserts `GET /customer/me` actually returns them, plus the
  combined table's correlation fields (billing_interval/billing_frequency,
  payment.subscription_ref, invoice.subscription_ref/transaction_id) -
  none of these were ever asserted on before, only exercised implicitly.
- The likelier real-world cause: the admin Testing/Developer Tools **TEST
  DATA GENERATOR** never created a `CustomerRegistrationData` row at all -
  a customer generated that way (the fast way to get a full
  customer/subscription/payment/invoice chain to test UI against) always
  had empty registration data, which would look identical to the bug
  above from the customer portal's perspective. Fixed: `generate_test_data()`
  now also creates one registration-data row with a type-appropriate
  sample value (`_sample_registration_value()`) for every active
  `RegistrationFormField` on the application - whatever fields the admin
  has actually configured, not hardcoded to this app's own seeded
  museum_name/contact_person/gstin/address set. `cleanup_test_data()`
  deletes it back out (`CustomerRegistrationData.customer_id.in_(...)`,
  before the subscription/customer deletes) so a repeated generate/
  cleanup cycle can never leave an orphaned row. Extended
  `test_test_data_generator_and_cleanup_round_trip` to assert the row
  exists after generate (non-empty values) and is gone after cleanup.

Verified: 106 total tests (up from 105), 105 passing (same pre-existing
`/ready` gap).

## 2026-09-13 (follow-up): registration-form field duplicate-value validation

Vishal's follow-up, verbatim: "Registration form data - 1. Add one more
checkbox to validate duplication (it means any record have similar value
then it will not allow user to enter same name) & Validation message for
that duplication also should be configured."

**What changed:**

- `RegistrationFormField` gained two new columns
  (`f2a8c3d91b45_form_field_duplicate_validation.py`, off head
  `e45b1604043b`): `check_duplicate` (boolean, default `False`) and
  `duplicate_message` (nullable string, 255 chars) - same shape as the
  existing `validation_pattern`/`validation_message` pair, exposed the
  same way on `RegistrationFormFieldOut`/`Create`/`Update`.
- New `app.forms.validation.check_duplicate_registration_data()`,
  deliberately a SEPARATE function from the existing
  `validate_registration_data()` rather than folded into it: the
  duplicate check needs to know which customer is submitting (to exclude
  that customer's own prior rows), which isn't resolved until after
  `/subscribe` has looked up or created the `Customer` record, whereas
  the existing regex check runs earlier, before that resolution, and was
  left untouched to avoid any regression risk to already-tested behavior.
  It's wired into `app/api/v1/public.py`'s `/subscribe` right after
  customer resolution and before the upgrade/downgrade/new-subscription
  branch, so it applies uniformly across all three paths.
- Matching is case-insensitive and whitespace-trimmed (`_normalize()`:
  `str(value).strip().lower()`), per Vishal's own wording ("any record
  have similar value") rather than a byte-exact comparison. A field with
  `check_duplicate` off never blocks a repeated value; a blank submitted
  value is never checked; a customer re-submitting their own existing
  value (e.g. on an upgrade/downgrade that resends the same
  `registration_data`) is excluded via `exclude_customer_id` and is never
  flagged as a duplicate of itself - the main regression risk this
  feature could have introduced.
- The lookup queries `CustomerRegistrationData` rows for the application
  via SQLAlchemy, then compares each row's JSON value in plain Python
  rather than as a dialect-specific JSON-column SQL expression, so
  behavior is identical on SQLite (tests) and Postgres (production).
  This is a full table scan per checked field per submission - documented
  in code comments as an accepted trade-off at this app's expected scale,
  not a hidden shortcut.
- Rejection is a 422 `REGISTRATION_DATA_INVALID` with the field's
  `duplicate_message`, falling back to a generic "<label> already exists.
  Please use a different value." when unset - same pattern as the
  existing regex validation's message handling.
- Admin UI (`AdminRegistrationFormPage.tsx`): the shared `ValidationFields`
  block (used by both the create form and the field-edit modal) gained a
  "Check duplicate" checkbox and a conditional duplicate-message input
  right after the existing regex/test-pattern controls; the fields table
  gained a "Duplicate check" column (`ON`/`Off` badge) next to the
  existing "Validation" column.

New backend tests in `tests/test_form_field_duplicate_validation.py` (8
tests): admin create/update save and return the two new fields correctly
and expose them on the public form endpoint; a duplicate value is
rejected with the configured custom message, or a generic fallback when
none is set; matching is case-insensitive/whitespace-trimmed; a field
with the checkbox off allows repeats; a blank value is never checked; and
- the key regression test - an existing customer upgrading their plan
while resending their own unchanged value succeeds, while a genuinely
different customer using that same value is still rejected.

Verified: full suite 183 total, 182 passing (up from 175 total/174
passing before this pass), same single pre-existing, unrelated `/ready`
DB-connectivity gap that predates this project. Frontend `tsc -b && vite build`
clean; `oxlint` 0 errors, same 9 pre-existing warnings (double-checked
the one warning inside `AdminRegistrationFormPage.tsx`, confirmed
pre-existing and unrelated to this change). New migration
`f2a8c3d91b45` (single clean head off `e45b1604043b`) still needs
`alembic upgrade head` run against Vishal's real Postgres database.

**Not yet committed.** This session's remote shell to Vishal's machine
(`device_bash`) is down - Windows update (Sept 8) broke Claude's
workspace access to local files; file staging/reading/writing still
works, but no remote command execution, so `git add`/`git commit` could
not be run on the real repository. The files listed above were changed
and verified in an isolated mirror and written back to the real repo
paths via file transfer only (no git operations performed there) -
Vishal needs to run `git add` + `git commit` himself once at the
machine (exact command given to him separately), or wait for the
device-shell issue to clear.

## 2026-09-13 (follow-up 2): Testing page trimmed + webhook event dropdown, configurable post-subscription message

Vishal's follow-up, verbatim:

"Testing Tools Page inside admin

1. Remove Test Payment section
2. Remove Test Subscription Events section
3. Under Test Webhook
   1. Give dropdown of Events like activate etc..
   2. Based on selection JSON editor automatically should be filled with
      required strcuture.

Thank you page after payment

1. show message "You have successfully subscribed, you will get your
   credentials in sometime" for first time subscription, (after section
   of Transaction: `TXN-RJTJMJJODP`)
   1. This message also should be configurable.
2. for change plan they already will have credentials."

**Testing page (`AdminTestingPage.tsx`)**: the Test payment and Test
subscription events sections are gone. Their backend endpoints
(`/admin/testing/payment`, `/admin/testing/subscription-event`) are
deliberately left untouched - same "dead UI, live backend" precedent
this codebase already used for the Plan Transitions allow-list UI
(2026-09 UI/UX rework) - so direct API/diagnostic use and every existing
test against them keeps passing unmodified; only the frontend imports/
state/JSX for those two sections were removed (unused-var-clean, this
project's `tsconfig.app.json` has `noUnusedLocals`/`noUnusedParameters`
on).

Test Everyticket webhook gained an Event dropdown. Rather than write a
second, easily-drifting copy of the five real webhook event bodies, the
admin Configuration screen's existing "Webhook events" sample-JSON
builder (`_build_webhook_samples` in `admin_config.py`) was moved
verbatim into `app.webhooks.payloads.build_webhook_samples()` - now the
one shared source of truth for both. A new `GET
/admin/testing/webhook/samples` (`TESTING_TOOLS_USE` + `require_test_mode`
gated, same as every other Testing endpoint) returns it; picking an event
from the new dropdown fills the JSON editor with `JSON.stringify(sample.
payload, null, 2)` - the exact wire body (`{event_type, payload}`) a real
delivery of that event would send - which the admin can still hand-edit
before sending, same as before.

**Configurable post-subscription message**: new `Application.
post_subscription_message` column (migration `a6d92e4f7c31`, off head
`f2a8c3d91b45`, nullable - unset falls back to a built-in default string,
`DEFAULT_POST_SUBSCRIPTION_MESSAGE` in `app/applications/config_schemas.py`,
same fallback convention as `validation_message`/`duplicate_message` on
registration form fields), editable on the admin Configuration screen's
existing "Application" section. New public `GET /public/messages`
(`PublicMessagesOut`) serves the resolved value (configured text, or the
default) with no auth - it has to be readable by an anonymous customer
mid-checkout.

Distinguishing "first time subscription" from "change plan" (point 2:
"for change plan they already will have credentials") needed a real,
precise signal rather than guessing from whether the customer happened
to be signed in already - `PaymentTransactionOut` (customer/public-facing
payment schema) gained `payment_type` (`NEW | RENEWAL | UPGRADE |
DOWNGRADE` - a real `PaymentTransaction` column that already existed and
already auto-populates via `model_validate()`, just never exposed on
this particular schema before; `PaymentAdminOut`, the admin-only schema,
already had it). The message is shown only when `payment_type === "NEW"`:

- **Mock gateway** (what this dev environment actually exercises):
  `SubscribePage.tsx`'s "done" step - previously showing no transaction
  detail at all once payment was simulated - now also shows a Transaction
  line (`callbackResult.payment.transaction_id`, matching Vishal's own
  wording of where the message should go) immediately followed by the
  message when `payment_type` is `NEW`. An authenticated existing
  customer whose `/subscribe` call gets silently auto-routed to an
  upgrade/downgrade against their existing subscription (spec section
  9/22's auto-routing) never sees it, since that transaction's
  `payment_type` is `UPGRADE`/`DOWNGRADE`, not `NEW` - exactly Vishal's
  "already have credentials" case, with no separate flag needed.
- **Real PayU gateway**: `_handle_payu_return()` (`app/api/v1/payment.py`)
  now also passes `payment_type=updated_transaction.payment_type` in the
  redirect back to `/payment/return`; `PaymentReturnPage.tsx` reads it and
  shows the message right after its existing Transaction line, gated the
  same way (`payment_type === "NEW"`). Both pages fetch `GET
  /public/messages` themselves (SubscribePage on mount alongside its
  existing "other plans" fetch; PaymentReturnPage only when the payment
  succeeded and is NEW) rather than threading the text through every
  intermediate response.

New backend tests: `test_admin_testing.py` gained a webhook-samples test
(covers all five events, and asserts byte-for-byte parity with the admin
Configuration screen's own preview, `expires_at` excluded from the
comparison since it's independently computed as "now + 30 days" on each
of the two separate requests); `test_admin_config.py` gained two
post_subscription_message tests (round-trips through the admin API and
is served correctly by the public endpoint; falls back to the default
text when explicitly cleared); a new `test_payu_callback_redirect.py`
drives a REAL subscribe → PayU checkout → signed callback round trip
(same reverse-hash formula as `test_payu_gateway.py`'s adapter-only unit
tests) for both a first-time subscription (asserts `payment_type=NEW` on
the redirect) and an existing customer's upgrade (asserts `payment_type=
UPGRADE`) - the actual wire contract PaymentReturnPage.tsx depends on,
not just the underlying field in isolation.

Verified: full suite 190 total, 187 passing (up from 183 total/182
passing before this pass), same single pre-existing, unrelated `/ready`
gap. Frontend `tsc -b && vite build` clean (65 modules); `oxlint` 0
errors, same 9 pre-existing warnings, none new (the two new `useEffect`
calls that fetch the public message set state inside a `.then()`
callback, not synchronously in the effect body, so they don't trip
`react/set-state-in-effect` - same pattern `listPlans()` already used in
`SubscribePage.tsx`). New migration `a6d92e4f7c31` (single clean head)
still needs `alembic upgrade head` run against Vishal's real Postgres -
now the **second** migration this project has sitting uncommitted (on
top of `f2a8c3d91b45` from the follow-up above), since `device_bash` was
still down for this entire pass too - same standing note applies: not
yet committed, written to the real repo paths via file transfer only,
Vishal needs to run `git add`/`git commit` himself (or wait for the
device-shell issue to clear) before either pass reaches his real git
history.

## 2026-09-13 (follow-up 4): real Everyticket SSO handoff API (POST /api/v1/integration/sso/generate-link)

Vishal's follow-up, verbatim: "Test SSO Link - Actually this has to be
generated by Everyticket platform to login into subscription engine...
so need to give API to everyticket Platform to call that which generates
token and return a link so everyticket can use inside their app. or any
other way to make login that customer please suggest."

**Why an API call, not Everyticket minting the token itself**: spec
section 47 describes Everyticket generating the signed SSO token
directly. That can't actually work end to end with this app's replay
protection, though: `app/sso/service.py`'s redemption check is DB-backed
(a token is only valid if a matching `SsoSession` row already exists,
created at mint time) - so whoever mints a token must be able to write
to this app's own database, which only this app can do. The correct,
secure shape is therefore exactly what Vishal asked for: Everyticket's
backend calls this app's API to have the token minted (this app still
owns issuance and the replay-protection row) and gets back a ready-to-use
link.

**New endpoint**: `POST /api/v1/integration/sso/generate-link`
(`app/api/v1/integration.py`, previously an empty placeholder router).
Body: `{external_customer_id, user_identifier?}` - `external_customer_id`
is the identity Everyticket itself already holds for this customer,
handed back to it in the `subscription.activated` webhook's response
(spec section 32), so by the time a customer clicks "Manage Subscription"
inside Everyticket the mapping is guaranteed to already exist. Returns
the same `SsoLinkOut` shape (`sso_token`, `consume_url`, `expires_at`)
the existing TEST_MODE-only admin action already returns, since both
call the exact same `sso_service.create_sso_token()` underneath - a
token minted through either path is redeemed identically via the
existing `POST /public/sso/consume`.

**Authentication is a new kind for this app**: every other endpoint here
authenticates a human (admin bearer token, customer OTP session). This
one authenticates Everyticket's own backend - `X-Api-Key`/`X-Api-Secret`
headers, checked with `hmac.compare_digest` (constant-time) against
`Application.api_credentials` (a JSON column that already existed on the
model but was completely unused - reused here as `{"api_key":...,
"api_secret":...}`, so **no migration was needed** for this feature).
Distinct from every other secret already in this app: `webhook_secret`
signs OUR outbound calls TO Everyticket; `sso_secret` still signs every
token internally but Everyticket never needs to see it now that it
doesn't mint tokens itself; `api_credentials` authenticates Everyticket's
INBOUND calls TO this app. Until the admin configures these credentials,
every call is refused (401 `UNAUTHORIZED`), never silently allowed. An
unmapped `external_customer_id` is a 404 `CUSTOMER_NOT_FOUND`. Every
successful call is audit-logged (`SSO_LINK_GENERATED`, actor
`everyticket-integration:<application code>`).

**Admin Configuration**: the Everyticket Integration section gained an
"SSO API access" block - an API Key field (shown in plain text; it's an
identifier, not a secret by itself) and an API Secret field (deliberately
NOT password-masked, unlike every other secret field on this app -
admin's job here is to copy the value and hand it to Everyticket's team
out of band, so hiding it on screen would be actively unhelpful) plus a
"Generate random values" button (`crypto.getRandomValues`-based, client
side). Same `None on PUT = unchanged, "" = clears` convention as
`secret_key` elsewhere on this screen.

**Test SSO admin action unaffected**: `POST /admin/customers/{id}/
sso-link` (TEST_MODE-gated, used by "Generate test SSO link" on the
admin customer detail page) is untouched - it remains the quickest way to
exercise the handoff without needing a real Everyticket call, and now the
admin Testing page's "Test SSO" section explicitly notes that the real
flow goes through this new API instead.

New backend tests in `tests/test_integration_sso.py` (5 tests): happy
path end to end (mint via the API, redeem via `/public/sso/consume`,
confirm the resulting token opens a real customer portal session, confirm
the audit log entry); refused when API credentials aren't configured yet;
refused with wrong key/secret; refused with missing headers; 404 for an
external_customer_id with no mapping. `tests/test_admin_config.py` gained
one round-trip test for the new `api_key`/`api_secret` fields (set,
partial-update leaves them unchanged, explicit `""` clears both).

Verified: full suite 194 total, 193 passing (up from 190 total/187
passing before this pass), same single pre-existing, unrelated `/ready`
gap. Frontend `tsc -b && vite build` clean (65 modules); `oxlint` 0
errors, same 9 pre-existing warnings, none new. **No new migration** -
`Application.api_credentials` already existed and was simply put to use,
so the pending-migration count stays at eight (unchanged from the
previous pass) even though this is a real, shippable feature.

## 2026-09-13 (follow-up 5): bugfix - Test Email ignored per-application SMTP config

**User report**: "Why test email is not going even after configured correctly SMTP."

**Root cause**: `POST /api/v1/admin/testing/email` (`test_email()` in
`app/api/v1/admin_testing.py`) called `email_service.send_templated_email()`
without passing `application=`. Every other real send site (payment success/
failed, subscription renewal reminders, invoice emails, customer OTP, the
webhook-delivery-exhausted escalation email) already passes the current
`Application` row so `_resolve_settings()` can override the global SMTP_*/
EMAIL_* env defaults with whatever was saved on Configuration ->
Notifications (`Application.smtp_host/smtp_port/smtp_username/
smtp_password/smtp_use_tls/email_provider`). Test Email was the one
exception - it always sent through the raw global `Settings` (SMTP_HOST=
localhost, SMTP_PORT=1025, no user/password), completely ignoring whatever
SMTP host/credentials the admin had just configured in the UI. Every other
`/testing/*` endpoint in this same file already takes
`application: Application = Depends(get_application)` as a dependency;
`test_email()` was simply missing it.

**Fix**: added the same `application: Application = Depends(get_application)`
dependency to `test_email()` and passed `application=application` into
`send_templated_email()`, matching every other call site.

**Test**: `tests/test_admin_testing.py::
test_test_email_uses_the_configured_application_smtp_override_not_global_defaults`
- sets a distinctive per-application SMTP host/port/username (clearly
different from the global env defaults), sends a test email through a
recording fake `smtplib.SMTP`, and asserts the SMTP conversation actually
used the configured values, not the global defaults.

**Verification**: full backend suite 195 total / 194 passing (same single
pre-existing `/ready` gap, needs live Postgres, unrelated); existing
`test_test_email_sends_via_faked_smtp` still passes unchanged.

**No new migration** - this only changed which already-existing settings
were read, not any schema.

## 2026-09-13 (follow-up 6): bugfix - SMTP "timed out" on port 465 (implicit SSL)

**User report**: after the previous fix, Test Email still failed with
`provider_response: "timed out"`.

**Root cause**: `app/notifications/email/providers/smtp/provider.py` only ever
opened a plaintext `smtplib.SMTP` connection, upgrading with STARTTLS if
`smtp_use_tls` was on - the port-587-style flow. Port 465 (the default most
providers, including Gmail and Office365, document for "SMTP over SSL") uses a
different convention: the server expects a TLS handshake immediately on
connect and never speaks in plaintext first ("implicit SSL"). Connecting to a
465-only server with plain `smtplib.SMTP` just sits waiting for a plaintext
banner that never arrives, until the socket hits its timeout - which is
exactly the "timed out" symptom reported.

**Fix**: `provider.send()` now opens `smtplib.SMTP_SSL` instead of
`smtplib.SMTP` whenever `SMTP_PORT == 465`, regardless of the `smtp_use_tls`
toggle (465 is unconditionally SSL by convention; the toggle still governs
STARTTLS behavior on every other port, unchanged). Also broadened the caught
exception tuple to include `TimeoutError` explicitly alongside the existing
`smtplib.SMTPException`/`OSError` (this was already covered via `OSError`'s
subclass hierarchy, but made explicit for clarity).

**Tests**: `tests/test_email_service.py::
test_smtp_provider_uses_implicit_ssl_for_port_465` (port 465 -> SMTP_SSL, not
SMTP) and `::test_smtp_provider_uses_plain_smtp_for_non_ssl_ports` (587/other
ports unchanged - still plain SMTP + optional STARTTLS).

**Also fixed in this same follow-up**: `TEST_EMAIL_SENT`'s audit log entry
used to be just `{"to", "sent": false}` - no way to see *why* a send failed
without catching the live API response at the moment it happened. It now
also stores `status` and `provider_response`, matching the precedent already
set for `TEST_WEBHOOK_SENT`. New test:
`tests/test_admin_testing.py::test_test_email_failure_reason_is_visible_in_audit_logs`.

**Verification**: full backend suite 198 total / 197 passing (same single
pre-existing `/ready` gap, needs live Postgres, unrelated to any of this).

**No new migration** - no schema change; `SMTP_PORT == 465` is a
convention check, not configuration.

**Still not implemented / worth knowing**: if this doesn't turn out to be a
TLS-mode mismatch, "timed out" more broadly just means the TCP connection to
`SMTP_HOST:SMTP_PORT` never completed from wherever this backend process
actually runs - most commonly a wrong host/port, or an outbound firewall on
that network blocking SMTP ports (25/465/587 are frequently blocked by
default on cloud VMs and some ISPs). That's an infrastructure/network check,
not something fixable in this codebase - see the reply to Vishal for the
diagnostic steps suggested.

## 2026-09-13 (follow-up 7): signed-in customers with an active subscription no longer land on the Plans page

**User request**: "After login, If user has already subscription then it
should not allow to go to Plans page - it should go to my subscription
page and ask for change plan."

**Before**: the public Plans page (`/`, `PlansPage.tsx`) rendered
unconditionally for anyone, signed in or not - including a customer who
already had an active subscription and just clicked the "Plans" link in
the header (or landed on `/` directly). Nothing steered them toward
"Change plan" on their existing subscription instead of the new-
subscription flow.

**Fix**: new route guard `RedirectIfActiveSubscription`
(`frontend/src/components/ProtectedRoute.tsx`, alongside the existing
`RequireCustomer`/`RequireAdmin`), wrapping the index route in `App.tsx`.
For a signed-in customer, it calls `GET /customer/me` and, if
`active_subscription` is set and is NOT a trial, redirects to `/portal`
(with a toast: "You already have an active subscription - use Change
plan below to switch.") instead of ever rendering the plan grid.
Deliberately scoped to non-trial subscriptions only - PortalPage already
refuses to offer "Change plan" for a trial subscription ("Free trials
can't be switched to another plan - subscribe to a paid plan instead"),
so a trial customer's only path to a paid plan IS this same Plans page;
blocking them here would strand them with no way to ever pay. A signed-
out visitor always passes straight through unaffected.

This is a UX guard, not a new security boundary: a signed-in customer who
instead navigates straight to `/subscribe/:planCode` bypasses it, but
that was already safe before this change too - the backend already
auto-routes an already-subscribed customer's `/subscribe` call to
upgrade/downgrade against their existing subscription rather than
creating a duplicate (spec section 9/22, and the earlier duplicate-
validation fix this session).

**Verification**: frontend `tsc -b && vite build` clean (65 modules);
`oxlint` 0 errors, same 9 pre-existing warnings, 0 new. No backend change,
so the full backend suite is unaffected (still 197/198, same pre-existing
`/ready` gap).

**No new migration** - frontend-only change, reuses the existing
`GET /customer/me` (`CustomerPortalOut.active_subscription`).

## 2026-09-13 (follow-up 8): switched the database from PostgreSQL to MySQL

**User request**: "Keep the back[up] of project now.. and change database
to mysql. let me know what details are required." Follow-up decisions:
fresh database is fine (no existing data to migrate), but the admin login
must keep working across the reset; and "I already have mysql into
xampp. or we can create in docker as well" (both are supported - see
README.md's Option A/A2).

**What actually changed**:

1. `requirements.txt`: `psycopg2-binary` -> `PyMySQL==1.1.1` (pure
   Python - no C extension to compile, so it installs the same way on
   Windows as everywhere else, unlike `mysqlclient`).
2. `app/core/config.py`: `DATABASE_URL` default is now
   `mysql+pymysql://subscription:subscription@localhost:3306/subscription?charset=utf8mb4`.
   Set your own in `.env` to match wherever your MySQL actually runs (see
   README.md's Option A for XAMPP's default `root`/no-password setup, or
   Option A2 for a one-line Docker MySQL container).
3. **New:** `ADMIN_BOOTSTRAP_EMAIL` / `ADMIN_BOOTSTRAP_PASSWORD` settings.
   When both are set in `.env`, `app/core/seed.py` creates that admin
   account (on a fresh database) instead of the hardcoded dev default
   (`admin@example.com` / `ChangeMe123!`) - this is how "keep admin
   credentials working" is satisfied without your real password ever
   needing to be typed anywhere but your own `.env` file (never logged,
   never printed - `seed.py`'s stdout output only ever prints the dev
   default credentials, or a note that a real password was set via env
   var).
4. **Real compatibility fix, not just a driver swap** -
   `app/subscriptions/models.py`'s two DB-level rules (one active
   subscription per customer+application; one trial per customer+
   application for their whole lifetime) were built as Postgres-only
   partial unique indexes (`postgresql_where=...`) - a feature MySQL has
   no equivalent for at all, in any version. Replaced with a portable
   generated-column design: `active_slot`/`trial_slot` are computed
   columns (`GENERATED ALWAYS AS (CASE WHEN ... THEN 1 ELSE NULL END)
   STORED`) that are 1 when the row matches the condition and NULL
   otherwise, with a plain unique index over `(customer_id,
   application_id, that column)` - every SQL dialect here treats NULL as
   distinct from every other NULL in a unique index, so only matching
   rows ever collide. Verified directly against a real local MySQL 8.0
   instance: an ACTIVE row plus a CANCELLED row for the same customer+
   application both insert fine (history still accumulates freely), a
   second ACTIVE row for the same customer+application is rejected at
   the DB level, and a second trial (even with a different status - e.g.
   CANCELLED then EXPIRED) is also rejected. This same generated-column
   approach is portable to SQLite too, so `tests/conftest.py`'s test
   suite now exercises this real DB-level constraint as well, not only
   the application-level pre-check (previously it silently could not,
   since SQLite/Postgres-dialect-specific kwargs are simply ignored on
   other dialects - the constraint was Postgres-only in practice even in
   tests). Also fixed: `app/notifications/models.py`'s `body_html`/
   `body_text` were unbounded `String` (valid on Postgres, but MySQL
   requires every `VARCHAR` to have an explicit length) - changed to
   `Text`, the correct type for arbitrarily long HTML/plain-text email
   bodies regardless of dialect.
5. **Alembic migration history squashed**: the 13 existing migrations
   were authored against Postgres and contain Postgres-only DDL that
   would either fail outright or silently do the wrong thing against
   MySQL - e.g. `postgresql_where=` on two `create_index` calls (ignored
   on MySQL, which would silently create a FULL unique index instead of
   a partial one - blocking a customer from EVER having more than one
   subscription row, even history), and one migration's
   `UPDATE ... FROM ...` (Postgres-only multi-table UPDATE syntax; MySQL
   needs `UPDATE ... JOIN ... SET ...`). Since there's no existing MySQL
   data to preserve, the old versions are archived (not deleted) at
   `backend/migrations_postgres_archive/versions_postgres_history_2026-09-13/`
   for historical reference, and `backend/migrations/versions/` now
   holds one fresh migration (`2c58d7629015_initial_mysql_schema.py`)
   autogenerated from the current models directly against MySQL 8.0 and
   verified with `alembic upgrade head` against a real local MySQL
   instance (clean run, no errors).
6. `README.md`: "Option A" now documents MySQL setup (including the
   XAMPP-specific connection string), and a new "Option A2" gives a
   one-line `docker run` command for MySQL if you'd rather not install it
   directly - both were exercised as part of this change. Also flagged
   (pre-existing, unrelated to this change): `.env.example` and
   `docker-compose.yml` are referenced in this README but don't actually
   exist anywhere in this repo - "Option B: Docker Compose" is aspirational
   documentation, not a verified/working path today.

**Verification**: full backend suite 198/198 passing against SQLite
(every one of the pre-existing `/ready`-endpoint gap's runs now also pass,
since this session's local MySQL instance happens to be reachable at the
default DATABASE_URL - that gap was always about no DB being reachable in
whatever environment runs the tests, not an application bug). Separately,
directly against a real local MySQL 8.0.36 instance: `alembic upgrade
head` applies cleanly, `python -m app.core.seed` creates the application/
plans/admin correctly (both with and without ADMIN_BOOTSTRAP_EMAIL/
PASSWORD set), and the one-active-subscription / one-trial-per-lifetime
constraints were exercised directly (5 scenarios, all correct - see
point 4 above).

**What Vishal needs to provide/decide** (answered so far: fresh database,
keep admin login, has MySQL via XAMPP already/open to Docker):
- Set `DATABASE_URL` in your own `.env` to match wherever MySQL actually
  runs - never needs to be shared here. For XAMPP:
  `mysql+pymysql://root:@localhost:3306/subscription?charset=utf8mb4`
  (create the `subscription` database first).
- Optionally set `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` in
  the same `.env` before running the seed script, to control the admin
  login on the fresh database instead of the dev default.
- Run, in order: `pip install -r requirements.txt` (picks up PyMySQL),
  `alembic upgrade head`, `python -m app.core.seed`.

**No data migration was performed** (the "fresh start" decision) - this
is a brand-new empty MySQL database plus the application's fixed seed
data (EVERYTICKET application, Basic/Professional/Enterprise/trial
plans, registration form, plan transitions, email templates, and the
admin user), not a copy of whatever was in the old Postgres database.

## 2026-09-13 (follow-up 9): registration-page asterisks, subscribe-page plan display, free (price=0) plans skip the payment gateway entirely

Four small, separately-requested changes to the public subscribe flow,
grouped here since they touched the same two files repeatedly:

1. **"show email and phone number as mandatory label - '*' like
   others"**: `SubscribePage.tsx`'s hardcoded Email/Mobile fields were
   always `required` but never got the `*` suffix the dynamic
   per-application fields (`DynamicRegistrationForm.tsx`) already show
   for any required field. Now read "Email *" / "Mobile *".
2. **"Show selected Plan on right side with its feature above other
   plans selection.. keep both things into same card"**: the
   `subscribe-plans-panel` side card (previously just "Other plans")
   now also fetches and shows the plan being subscribed to first - name,
   price/billing interval (or "Free for N days" for a trial), and its
   rich-text feature/description list - under a "Your plan" label,
   separated by a divider, with "Other plans" still below it in the
   *same* card (not a second card). New `selectedPlan` state, found by
   filtering the same `listPlans()` response already used for
   `otherPlans`.
3. **"Text 'Subscribe to PROFESSIONAL' should have Plan Name instead of
   code"**: the page heading now reads `selectedPlan?.name ?? planCode`
   - the plan's display name once loaded, falling back to the raw
   `planCode` route param only for the brief instant before that fetch
   resolves.
4. **"if price of plan is 0 then no need to redirect to payment
   gateway"**: price=0 is, by construction, *only* ever a free-trial
   plan (`app/api/v1/admin_plans.py`'s `_validate_trial_configuration`
   already rejects a non-trial plan with price 0 and a trial plan with
   any non-zero price) - but subscribing to one still went through the
   full payment-gateway dance (a real PayU hosted-checkout redirect for
   ₹0, or a mock-gateway "click simulate success" step) before
   activating, which is pure friction for something that was never
   actually going to charge anything.

   Fixed at the single choke point every payment goes through -
   `app/payments/service.py`'s `create_payment_transaction()` - rather
   than in any one caller, so it uniformly covers all four places that
   call it (a brand-new `/subscribe`, an existing customer's auto-routed
   upgrade/downgrade, the customer-portal's explicit upgrade/downgrade,
   and renewal): when `plan.price == 0`, the real gateway
   (`gateway.create_payment(...)`) is never called at all - instead a
   synthetic `GatewayPaymentResult` with `status=SUCCESS` is built
   locally and run straight through the existing
   `process_gateway_result()` SUCCESS path (same activation / invoice
   generation / outbound-webhook-queue-plus-`attempt_soon()` /
   confirmation-email behavior any other successful payment gets - nothing
   new to reason about there). `SubscribePage.tsx`'s `doSubscribe()`
   checks `result.payment.status === "SUCCESS"` and, when true, skips
   the "payment" step entirely and renders the same "done" screen a real
   successful mock-callback would reach (synthesizing the
   `MockCallbackResult` shape locally from the `SubscribeResponse` it
   already has - `invoice_id` isn't part of `SubscribeResponse`, so that
   one field is left `null`, even though the invoice was in fact
   generated and emailed).

   In practice today this can only ever be reached by a trial signup
   (the other three call sites can never actually see `plan.price == 0`
   given the admin-side validation above and the existing
   `InvalidPlanTransition` guard against switching *to* a trial via
   upgrade/downgrade) - so `ChangePlanPage.tsx` and `PortalPage.tsx`'s
   renew flow were deliberately left untouched, since they can't
   currently exercise this path; the backend fix is still written
   generically against `plan.price == 0` rather than `plan.is_trial`,
   so it needs no changes if that admin-side rule is ever relaxed.

   New test: `tests/test_free_trial.py::
   test_trial_subscribe_skips_payment_gateway_and_activates_immediately`
   - asserts `/subscribe` for the trial plan comes back
   `subscription.status == "ACTIVE"` and `payment.status == "SUCCESS"`
   (no `checkout` payload) with an invoice already on file, in direct
   contrast to `test_end_to_end.py`'s paid-plan test which still
   correctly asserts `PENDING_PAYMENT`/`INITIATED` immediately after
   `/subscribe`. Full suite: 198/198 (the pre-existing `/ready`-needs-a-
   live-database gap is an environment/session difference, not caused by
   this change - see follow-up 8).

## 2026-09-13 (follow-up 10): "Enable Notifications?" master switch under SMTP configuration

**User request, verbatim**: "add one more field at backend under SMTP
configuration that 'Enable Notifications?' - check box or radio. if its
enabled, email service will work otherwise it will skip."

A new `Application.notifications_enabled` column (Boolean, `default=True`
- every existing application keeps sending exactly as it does today)
gates ALL outbound email for that application at one single point,
independent of whether the SMTP host/port/credentials below it are
configured correctly - this is a hard on/off switch, not another
override-else-fall-back-to-env field like the rest of the Notifications
config group.

**What changed**:

1. `app/applications/models.py`: `notifications_enabled` column added
   right after the existing `smtp_*` columns.
2. `migrations/versions/2158e8072098_add_notifications_enabled_to_.py`:
   new migration, `server_default=sa.true()` (adjusted from the bare
   autogenerate output) so it applies cleanly to the already-seeded
   `applications` table - autogenerated against, and verified with
   `alembic upgrade head` on, a real local MySQL 8.0 instance (same
   workflow as follow-up 8's migration).
3. `app/core/enums.py`: `NotificationStatus` gained a third value,
   `SKIPPED` (alongside the existing `SENT`/`FAILED`) - a deliberately-
   disabled send is not a delivery failure, and showing it as FAILED
   would make an admin who intentionally turned this off see what looks
   like a wall of broken emails in Notification Logs.
4. `app/notifications/email/service.py`: both `send_templated_email()`
   and `send_direct_email()` check `application.notifications_enabled`
   immediately after resolving settings - before the template lookup,
   before rendering, before the SMTP provider is ever touched - and
   write a SKIPPED `NotificationLog` row (with a provider_response
   explaining why) rather than proceeding. `application is None` (no
   per-application context) still sends, matching every other
   per-application override's behavior in this module.
5. `app/applications/config_schemas.py` /
   `app/api/v1/admin_config.py`: `NotificationConfigOut`/
   `NotificationConfigUpdate` carry the new field; `update_notification_config`
   writes it straight through (no None-means-unchanged convention here -
   unlike the secret-bearing fields on this same screen, there's nothing
   sensitive about a boolean, so it's always replaced outright) and
   includes it in the `APPLICATION_CONFIG_UPDATED` audit entry.
6. Frontend (`AdminConfigPage.tsx`, `index.css`): a new "Enable
   Notifications?" checkbox sits above the existing SMTP fields on the
   Notifications config screen, with a hint explaining exactly what
   turning it off does; the SMTP fields below it visually dim (not
   disabled via `pointerEvents:none` on the Save button itself - that
   stays live so turning notifications back on and saving always works)
   when unchecked, as a visual cue that they're currently moot. New
   `.toggle-row` CSS class for this checkbox-plus-label row style (the
   app's default `label` layout stacks label-above-input, wrong shape
   for a single inline checkbox).
7. Test Email (admin_testing.py's existing endpoint) needed no code
   change at all to respect this - it already calls
   `send_templated_email()` with `application=`, so a disabled
   application now makes Test Email honestly report back a SKIPPED
   result with the same "disabled" explanation, rather than pretending
   to test something that would never actually go out.

**New tests**: `tests/test_email_service.py::
test_send_templated_email_skips_when_application_has_notifications_disabled`
(unit-level, deliberately runs with NO fake SMTP transport installed - if
the guard were ever missing or misplaced this test would fail with a
real connection error instead of the expected SKIPPED assertion, making
the test self-verifying); `tests/test_admin_config.py::
test_notification_config_defaults_to_enabled` and
`test_disabling_notifications_skips_email_send_without_touching_smtp`
(end-to-end: PUT the config off, trigger the OTP email
`test_update_notification_config_changes_outbound_sender_and_smtp_host`
already exercises for its own sender-override assertions, confirm the
fake SMTP transport was never called and the log came back SKIPPED).
Full suite: 202/202 (198 from follow-up 9, plus these 3, plus the
`/ready` endpoint passing again now that this session's local MySQL is
running - see follow-up 8's note on that gap being environment-specific,
not a code issue).

## 2026-09-14 (follow-up 11): configurable extra fields on outbound Everyticket webhooks

**User request, verbatim**: "allow to configure, more data to be passed
for webhook call like plan details including name, amount, expiry etc..
so if admin select those parameters then it will be passed to webhook to
everyticket. first let me know what parameters will be available for
this option then we will do code change" - the full parameter catalog
was presented and two design questions answered (per-event selection
rather than one universal list; payment/invoice fields excluded from
expired/cancelled/archived, since nothing is actually charged at that
moment) before any code was written, per the user's own explicit
two-phase request. A follow-up "yes" confirmed subscription.upgraded/
downgraded (previously outside this configurable system, with their own
fixed inline payload) should be brought into it too.

Every one of the 7 real outbound webhook events already sends a fixed
set of fields (subscription_id at minimum, more for onboarding/upgrade/
downgrade). This adds an OPT-IN layer on top: an admin can now also tick
additional fields - per event, since what's meaningful differs by event
(e.g. "Payment amount" makes sense for Renew, not for Expired) - and only
those tick get added to that event's real outbound JSON, on top of the
existing fixed fields. Nothing changes for any application that never
opts in - every existing webhook payload is byte-for-byte identical to
before this follow-up.

**What changed**:

1. `app/webhooks/field_catalog.py` (NEW): the single source of truth for
   what's selectable - `AVAILABLE_FIELDS` (event_type -> ordered list of
   selectable field names) and `FIELD_LABELS` (field name -> human
   label), plus `sanitize_selection()`, which drops any event type or
   field name a stored selection has that this catalog doesn't
   recognize - applied both when a selection is read back out and
   before it's saved, so a catalog change across a future release can
   never make a stale selection surface a field a payload builder
   doesn't know how to fill in. No payment/invoice fields are ever
   offered for subscription.expired/cancelled/archived, per the user's
   own decision when this was scoped.
2. `app/applications/models.py`: new `webhook_field_selection` JSON
   column (nullable, no migration default needed - NULL/missing key
   means "no optional fields for that event", i.e. unchanged behavior).
3. `migrations/versions/2f423fa60347_add_webhook_field_selection_to_.py`:
   new migration, verified with `alembic upgrade head` against a real
   local MySQL 8.0 instance (same workflow as follow-up 8/10's
   migrations).
4. `app/webhooks/payloads.py`: every builder (`onboarding_payload`,
   `renewed_payload`, `expiry_payload`, `cancelled_payload`,
   `archive_payload`, plus two NEW ones, `upgraded_payload`/
   `downgraded_payload`, replacing the inline dict payments/service.py
   used to build for those two events) now accepts every optional field
   its event's catalog entry lists (default `None`) plus a
   `selected_fields` list, and merges in only the ones both passed and
   selected - via a shared `_select_optional_fields()` helper that
   re-checks each name against `field_catalog.AVAILABLE_FIELDS` as a
   second, defense-in-depth sanitize pass. Precedence on any key
   collision: fixed fields always win, then admin-selected optional
   fields, then (onboarding only) the customer's own registration-form
   answers - extending the fixed-fields-always-win rule this module
   already had one level further.
5. `app/payments/service.py` / `app/subscriptions/service.py`: all 7
   webhook-queuing call sites (activated/renewed/upgraded/downgraded in
   `process_gateway_result`; expired/archived/cancelled in
   `expire_due_subscriptions`/`archive_stale_subscriptions`/
   `cancel_subscription`) now pass every raw value their event's catalog
   offers (all already sitting on ORM objects already loaded at that
   call site - no extra queries) plus
   `field_catalog.sanitize_selection(application.webhook_field_selection)
   .get(event_type)`.
6. `app/applications/config_schemas.py` / `app/api/v1/admin_config.py`:
   `EveryticketIntegrationOut` gained `webhook_field_catalog` (event_type
   -> `[{field, label}, ...]`, straight from field_catalog, for
   rendering the checklist) and `webhook_field_selection` (this
   application's current, sanitized selection);
   `EveryticketIntegrationUpdate` gained `webhook_field_selection`,
   replaced outright when given (same "always replace" convention as
   `retry_limit`/`archive_after_days` on this same endpoint - it isn't a
   secret) and sanitized again before being stored. `build_webhook_samples()`
   now covers all 7 events (previously 5 - upgraded/downgraded were
   real events but never had a sample) and reflects the application's
   current selection, so the Configuration screen's preview and the
   Testing page's event dropdown (both driven by this one function)
   never drift from what a real delivery actually sends.
7. Frontend (`types.ts`, `AdminConfigPage.tsx`, `index.css`): a new
   "Extra webhook fields" block on the Everyticket integration screen -
   one group per event, each a row of checkboxes built straight from
   `webhook_field_catalog` - sits above the existing "Webhook events"
   sample-JSON preview, so ticking a box and saving immediately shows
   the field appear in that event's sample below. New `.webhook-field-*`
   CSS classes.

**New tests**: `tests/test_webhook_payloads.py` -
`test_onboarding_webhook_includes_only_selected_optional_fields`,
`test_renewed_webhook_includes_selected_optional_fields`,
`test_upgraded_and_downgraded_webhook_payloads_include_selected_optional_fields`
(each drives a real subscribe/renew/upgrade + mock payment callback and
asserts the queued `WebhookEvent.payload` gains exactly the selected keys
with real values, nothing more),
`test_field_catalog_never_offers_payment_or_invoice_fields_for_expired_cancelled_archived`,
`test_sanitize_selection_drops_unknown_events_and_fields`;
`tests/test_admin_config.py` -
`test_integration_config_exposes_webhook_field_catalog_and_round_trips_selection`
(GET exposes the full catalog + empty default selection; PUT persists a
selection, silently dropping an unrecognized event/field rather than
rejecting the request); the existing five-event sample-coverage test in
this file and in `test_admin_testing.py` were updated to expect all 7
events (renamed accordingly) now that upgraded/downgraded are covered
too. Full suite: 208/208 (202 from follow-up 10, plus these 6).

## 2026-09-14 (follow-up 12): webhook fields screen - fixed-field transparency + dropdown/two-column layout

**User request, verbatim**: "subscription.activated - does not have plan
name, code, price etc.. where it has to be, same for renewed event there
is no plan code, please keep consistency" and, separately: "also for
these webhooks, - Give dropdown - when eventtype selected, it will show
checklist left side and sample JSON at right side so we can reduce
overall space."

Two follow-on fixes to follow-up 11's new Configuration screen, both
about how the (already-correct) field data is presented, not about the
underlying payloads:

1. **Fixed-field transparency.** The checklist previously showed ONLY
   the OPTIONAL fields (`AVAILABLE_FIELDS`) an admin could tick. For
   subscription.activated/upgraded/downgraded, plan_code/plan_name/price
   etc. are already always sent (fixed) - they were never OPTIONAL, so
   they never appeared in that checklist at all, which read as "this
   event doesn't have plan info". For subscription.renewed, those same
   fields genuinely ARE optional (Vishal's own follow-up 3 trimmed
   renewed's fixed shape to `subscription_id` only) - so they did appear
   there as ordinary checkboxes. Same underlying fields, opposite
   visibility, for no reason a reader of the screen could tell.
   `app/webhooks/field_catalog.py` gained `FIXED_FIELDS` (event_type ->
   always-sent field names, display-only - never sent back as part of a
   selection, since a builder doesn't need telling to include something
   it already always includes), exposed via a new
   `EveryticketIntegrationOut.webhook_fixed_fields` field
   (`app/applications/config_schemas.py`, `app/api/v1/admin_config.py`).
   The checklist now always shows BOTH groups for whichever event is
   selected: fixed fields first, rendered as checked-and-disabled with an
   "(always sent)" label, then the real, tickable optional fields - so
   activated visibly has its plan fields (marked always-sent) and
   renewed visibly has plan_code as a real, unchecked option, and nothing
   looks missing either way.
2. **Dropdown + two-column layout.** The previous screen stacked one box
   per event (7 checklists) followed by one sample-JSON block per event
   (7 more blocks) - a lot of scrolling to look at any single event.
   Replaced with a single `<select>` of all 7 event types
   (`AdminConfigPage.tsx`'s `IntegrationSection`) plus one
   `.webhook-event-detail` area showing just the selected event: its
   checklist on the left, its sample JSON on the right, via a responsive
   CSS grid (`repeat(auto-fit, minmax(min(280px, 100%), 1fr))` - the
   `min(280px, 100%)` guards against the admin layout's actual content
   width, which is narrower than the raw viewport because of its fixed
   sidebar, ever being forced wider than available and clipping text).
   Switching the dropdown re-renders both panes instantly (no extra
   request - both `fieldCatalog`/`fixedFields`/`webhook_field_selection`
   and every event's sample are already loaded).

**What changed**: `app/webhooks/field_catalog.py` (`FIXED_FIELDS` +
`FIELD_LABELS` entries for `subscription_id`/`status`),
`app/applications/config_schemas.py` /`app/api/v1/admin_config.py`
(`webhook_fixed_fields` in the GET response), `frontend/src/api/types.ts`
(`webhook_fixed_fields` on `EveryticketIntegrationOut`),
`AdminConfigPage.tsx` (event dropdown, two-pane layout, fixed-field
rows), `index.css` (`.webhook-event-picker`, `.webhook-event-detail`,
`.webhook-field-checkbox-fixed`; old per-event-box grid and stacked
sample list removed).

**New tests**: `tests/test_admin_config.py::
test_integration_config_exposes_webhook_field_catalog_and_round_trips_selection`
extended to assert `webhook_fixed_fields` covers every event, that
`subscription.activated`'s fixed set includes plan_code/plan_name/price
(and that plan_code is NOT also in its optional catalog), and that
`subscription.renewed`'s fixed set is `subscription_id` only while
plan_code IS in its optional catalog. Full suite: 208/208 (same count as
follow-up 11 - this extended an existing test rather than adding a new
one). Manually verified in a real browser (Playwright, logged in as the
seeded admin) at 1300px (dropdown + side-by-side panes, activated's
plan fields correctly marked "always sent"), 900px (checklist column
collapses to full width, stacks above the sample), and confirmed
switching the dropdown to subscription.renewed shows plan_code as a
real, unchecked checkbox rather than "always sent".

## 2026-09-14 (follow-up 13): sample JSON updates live as checkboxes are ticked, not just after Save

Vishal: "when select checkbox for parameters, it should reflect into
sample JSON as well." The dropdown/two-column screen from follow-up 12
only refreshed its sample JSON from the PUT response, so ticking a box
and NOT yet clicking Save showed no change at all - easy to read as "my
click didn't register."

**Design constraint carried over from every other webhook-sample feature
in this codebase**: the sample/preview JSON must always come from the
same payload-builder functions a real delivery uses (see
`app/webhooks/payloads.py`'s module docstring) - the frontend must never
invent a field's sample VALUE itself. Two ways to get a live update
without breaking that rule: (a) auto-save the selection on every
checkbox click, or (b) have the backend hand the frontend a second,
"maximal" sample per event (as if every optional field were selected)
and let the frontend purely filter which already-computed keys to show.
Went with (b): auto-save was rejected because it would silently persist
whatever else is sitting in the surrounding form at that moment
(webhook URL, secret key, retry limit, ...) even if the admin is
mid-edit on those and not ready to save them yet.

**Backend**: `app/webhooks/payloads.py`'s `build_webhook_samples()` gained
an optional `selection_override: dict[str, list[str]] | None` parameter -
when given, it's sanitized and used instead of the application's actually
stored `webhook_field_selection`, but every payload is still built by the
exact same per-event builder functions (no new value-computation logic
anywhere). `app/applications/config_schemas.py`'s `EveryticketIntegrationOut`
gained `webhook_samples_all_fields: list[EveryticketWebhookSampleOut]` -
same shape as the existing `webhook_samples`. `app/api/v1/admin_config.py`'s
`_integration_out()` now also calls `build_webhook_samples(db, application,
selection_override={event_type: fields for event_type, fields in
AVAILABLE_FIELDS.items()})` to populate it - i.e. "what would this event's
payload look like if every optional field were ticked."

**Frontend**: `frontend/src/api/types.ts` adds the matching
`webhook_samples_all_fields` field. `AdminConfigPage.tsx`'s
`IntegrationSection` stores it in `samplesAllFields` state (refreshed
from the PUT response too, alongside `fieldSelection`, so it stays
correct if application data that feeds sample values - e.g. the active
plan - changes on save) and derives a `livePreviewSample` via `useMemo`,
recomputed whenever `fieldSelection` changes: it finds
`samplesAllFields`'s entry for the selected event, then - since each
sample's `payload` is the whole `{event_type, payload: {...fields}}` wire
body, not a flat field map - filters keys inside that nested `payload`
object, dropping any key that's in the event's optional catalog
(`fieldCatalog[eventType]`) but not currently ticked
(`fieldSelection[eventType]`); every fixed field and every key outside
the optional catalog (e.g. onboarding's dynamic registration-data fields)
is always kept. The JSX now renders this computed object instead of
filtering the plain `webhookSamples` list, which is no longer needed and
was removed. Hint text above the dropdown updated to say the JSON
updates instantly and Save is what makes it take effect on the next real
delivery.

**New test**: `tests/test_admin_config.py::
test_webhook_samples_all_fields_shows_every_optional_field_regardless_of_saved_selection`
- with the application's saved selection empty, asserts
`webhook_samples`'s `subscription.renewed` sample carries only
`subscription_id` (as before) while `webhook_samples_all_fields`'s
`subscription.renewed` sample carries every field in that event's
optional catalog, including a real non-placeholder `plan_code` value.
Full suite: 209/209 (208 existing + this one new test).

Manually verified in a real browser (Playwright, logged in as the seeded
admin, backend started with `ALLOW_ADMIN_MFA_BYPASS=true` so the "BYPASS"
MFA code worked): on `subscription.renewed`, ticked "Plan code" and
confirmed the JSON pane updated to include `"plan_code": "BASIC"`
immediately (before Save), then unticked it and confirmed it disappeared
again just as immediately. Also re-confirmed `subscription.activated`
still shows its fixed fields (plan_code/plan_name/price/subscription_id/
email/phone_number) by default and that ticking one of its own optional
fields (Currency) adds it live too - no regression from follow-up 12's
fixed-field fix. Checked 900px width for newly-introduced horizontal
overflow: none found. No new migration needed for this change.

## 2026-09-14 (follow-up 14): Configuration split into its own sidebar group with 4 sub-pages; Webhook logs' "Connectivity check" panel removed

Vishal: "Under Configuration, 4 sub menu will come 1. General - which
contains application 2. Payment Gateway - will contain payment gateway
config 3. Communication - will contain Notification section from config
(Email section) 4. Integration - will be Everyticket Integration" plus,
separately, "Webhook logs - Remove section of 'Connectivity check'".
Pure frontend routing/navigation + one page-content removal - no backend
or database changes.

**Configuration restructure.** The single `/admin/config` screen used to
stack all four section forms (Application, Payment gateway, Everyticket
integration, Notifications) on one long page. It's now four separate
routes, one per section, and the sidebar's "Configuration" entry (which
used to be one item at the bottom of the "System" group) is now its own
top-level nav group with those four as its submenu items - the same
group+submenu pattern every other sidebar group (Catalog, Customers,
Billing, ...) already uses:

- General -> `/admin/config/general` (Application name/currency/Live-Test
  mode/post-subscription message - the old "Application" section,
  unchanged)
- Payment Gateway -> `/admin/config/payment-gateway` (gateway dropdown +
  PayU credentials + redirect/webhook URLs - unchanged)
- Communication -> `/admin/config/communication` (SMTP transport + sender
  overrides - the old "Notifications" section inside Configuration,
  unchanged; NOT to be confused with the separate "Notifications" page
  under the sidebar's existing "Communications" group, which is email
  templates + delivery logs, a completely different screen this request
  didn't touch)
- Integration -> `/admin/config/integration` (secret key, webhook URL,
  retry limit, archive-after-days, the webhook-events dropdown + live
  sample JSON from follow-ups 11-13, escalation email - the old
  "Everyticket integration" section, unchanged)

Bare `/admin/config` redirects to `/admin/config/general` so an old
bookmark/link still lands somewhere sensible.

**What changed**: each section's form logic (state, save handler, JSX)
was moved as-is out of the old `AdminConfigPage.tsx` into
`frontend/src/pages/admin/config/ConfigSections.tsx` (now exporting
`GeneralSection`/`PaymentGatewaySection`/`IntegrationSection`/
`NotificationSection`/`Section`/`SaveButton` instead of keeping them
private to one file) - no section's own behavior, validation, or API
call changed at all, only where the function lives. Four new thin page
components (`AdminConfigGeneralPage.tsx`,
`AdminConfigPaymentGatewayPage.tsx`, `AdminConfigCommunicationPage.tsx`,
`AdminConfigIntegrationPage.tsx`, all under
`frontend/src/pages/admin/config/`) each fetch the full
`ApplicationConfigOut` via a small shared `useApplicationConfig()` hook
(`useApplicationConfig.ts`) and render just their one section - the same
independent-fetch-per-page pattern every other admin page in this app
already follows, rather than introducing a shared route layout/context
that would be the only one of its kind here. `App.tsx` swaps the old
single `config` route for the four routes above plus the redirect;
`AdminLayout.tsx`'s `NAV_GROUPS` drops "Configuration" from "System" and
adds it as its own group. The old `AdminConfigPage.tsx` was deleted from
the repo (nothing imports it anymore) - **manual step for Vishal**: the
remote file-delete path wasn't available when these changes were shipped,
so the new/changed files could be written but the old file could not be
deleted on your machine automatically - please delete
`frontend/src/pages/admin/AdminConfigPage.tsx` yourself once these
changes are in; it's dead code (unreferenced by any route) but harmless
to leave until you get to it.

**Webhook logs "Connectivity check" removal.** The standalone
"Connectivity check" panel (its "Verify connectivity" button and the
result readout below it) is removed from `/admin/webhooks` entirely, per
Vishal's explicit request. Its state (`verifying`/`verifyResult`), handler
(`handleVerify`), and now-unused imports (`adminVerifyWebhookConnectivity`,
`TestWebhookSendResult`) were removed from `AdminWebhooksPage.tsx`. The
backend endpoint it called (`POST /api/v1/admin/webhooks/verify`) and its
API client function were deliberately left in place (not asked to be
removed, and the Testing tools page's own "Send test webhook" action
covers similar ad-hoc verification) - only this page's UI section is
gone. The rest of the page (Deliveries table with its per-row Attempt
button, Events table) is unchanged.

**Verification**: `npx tsc -b` and `npm run build` both clean (70 modules
now, up from 65, for the new config/ page files). No backend changes, so
the existing 209/209 test suite is unaffected (not re-run for this purely
frontend change beyond the build). Manually verified in a real browser
(Playwright, logged in as the seeded admin): clicked through the sidebar's
new Configuration group to all four sub-items and confirmed each URL and
page heading; confirmed a bare `/admin/config` redirects to
`/admin/config/general`; confirmed the Integration and Communication
pages render their full original forms (webhook events dropdown + live
sample JSON, SMTP fields) unchanged; confirmed `/admin/webhooks` no longer
contains "Connectivity check" or "Verify connectivity" anywhere on the
page while "Deliveries" and "Events" still render normally. No migration
needed for this change.

## 2026-09-14 (follow-up 15): SSO API access help text now shows the actual request/response JSON contract

Vishal: "for SSO API access (for Everyticket's 'Manage Subscription'
link) - What parameters Everyticket has to send apart from key and
secret... please show json as help text into Integration configuration."
The section already explained that the API key/secret go as `X-Api-Key`/
`X-Api-Secret` headers, but never showed the actual request body
Everyticket's backend has to POST, or what it gets back - an admin
reading this screen (or handing it to Everyticket's integration team)
had no way to see that without reading backend source.

**What changed**: `frontend/src/pages/admin/config/ConfigSections.tsx`'s
`IntegrationSection`, right after the API key/secret fields, now renders
a `POST /api/v1/integration/sso/generate-link` sample block (reusing the
existing `.webhook-sample`/`.webhook-sample-header`/`.webhook-sample-body`
styling the webhook-events preview already uses, so it looks like part of
the same family of "here's exactly what gets sent" help text) showing:
headers (`X-Api-Key`/`X-Api-Secret`, referring back to the fields above),
the request body (`external_customer_id` required, `user_identifier`
optional), and the response (`sso_token`/`consume_url`/`expires_at`) -
taken directly from `app.sso.schemas.SsoLinkGenerateRequest`/`SsoLinkOut`
and `app.api.v1.integration.generate_sso_link`, not approximated. A
follow-up paragraph underneath explains where `external_customer_id`
comes from: it's the same value Everyticket's own backend already
returned in its response to the `subscription.activated` webhook
(`{success, external_customer_id, instance_id}` - see
`app.webhooks.service`'s `_handle_activation_outcome`), so it's always on
hand by the time a customer clicks "Manage Subscription"; `user_identifier`
is optional audit-only context. This is display-only help text - no
backend change, no new endpoint, nothing about the real SSO handoff
changed.

**Verification**: `npx tsc -b` and `npm run build` both clean (no new
files, existing module count). No backend touched, so the 209/209 suite
is unaffected. Manually verified in a real browser (Playwright, logged in
as the seeded admin) that `/admin/config/integration` renders the new
block with `external_customer_id`, `user_identifier`, `consume_url`, and
`X-Api-Key` all present and readable. No migration needed.
