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

## Explicitly NOT implemented yet

These are real gaps against the full spec, not hidden shortcuts - each is
called out in the relevant module's docstring too:

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
- Docs/README refresh: **done as of increment 14** (this pass) - `README.md`,
  `frontend/README.md`, and this file are all now current through
  increment 14.
- Everything above is unit-tested (97 tests) against SQLite; no end-to-end
  manual pass against a real Postgres + real PayU sandbox + a real
  Everyticket-shaped webhook receiver has been done in this environment -
  that's the natural next step once Vishal is ready to test, per his own
  standing instruction to test everything at the end.
