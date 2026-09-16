# Everyticket Subscription Management Platform

Standalone subscription management application for Everyticket (plans,
registration, payments, subscription lifecycle, invoicing, Everyticket
integration, admin/customer portals). Everyticket itself - ticketing,
booking, POS, etc. - is a separate application and is out of scope here.

**Current status:** Phase 1 is functionally complete against the master
spec's ~90 sections - a working new-subscription -> payment -> active ->
invoice flow (mock gateway AND a real PayU hosted-checkout integration,
hash-verified both ways), admin login + MFA + a full permission-gated
admin CRUD API/UI (plans, customers, subscriptions, payments, invoices,
webhook logs, notification templates/logs, audit logs, dashboard,
registration-form fields, plus Payment Gateway/Everyticket
Integration/Notification/Subscription-Rules/Security configuration
screens), duplicate customer detection + OTP verification with real
email delivery, customer-portal upgrade/downgrade/renew/cancel (each
individually admin-disable-able, and actually enforced), outbound
Everyticket webhook dispatch with retry, Celery-beat-scheduled
subscription expiry + renewal reminders, a dynamic per-application
registration-form renderer, Everyticket SSO (signed single-use tokens,
DB-backed replay protection, a TEST_MODE admin action to generate a
working test link), and a full admin Testing/Developer Tools module
(test payment simulation, test subscription events, a live webhook
sender, a webhook failure/retry simulator, test email sending, test SSO,
OTP/MFA bypass toggles, and a test-data generator + cleanup - all
TEST_MODE- and permission-gated) - an authenticated existing customer calling /subscribe for a
different plan is now auto-routed to an upgrade/downgrade against their
existing subscription instead of a flat refusal, and OTP resend requests
are rate-limited. Invoices carry real GST/tax calculation from an
admin-configurable rate, PDF generation (rendered once, cached to disk),
admin+customer download, and automatic-plus-on-demand email delivery
with the PDF attached. Everyticket's response to the initial activation
webhook is parsed for real (spec section 32): a successful response
stores the returned external_customer_id/instance_id against the
customer, while a failure (network error, non-2xx, or an explicit
success:false body) sets the subscription's provisioning_status to
FAILED, retries automatically on the same webhook backoff schedule, and
emails the customer once - all without ever touching the
payment/subscription's own status (spec section 30) - all backed by a
real MySQL schema (switched from PostgreSQL 2026-09-13) and an automated
test suite (`pytest tests/ -v` - see docs/implementation-status.md for
the current count), plus hand-verified via curl against real MySQL. Plan descriptions are
now rich text (a bullet-point-capable editor, sanitized server-side with
a `bleach` allowlist and rendered formatted on the public plan listing),
plans support drag-and-drop-or-arrow-button reordering that's persisted
and reflected on that same public listing, and every admin/customer
mutating action across the app now surfaces a toast notification in
addition to its existing inline error/success feedback. A React frontend
covers the public subscribe flow (dynamic registration form; mock
simulate buttons or a real PayU checkout redirect, depending on the
application's configured gateway), customer OTP login + portal + SSO
landing page, and the full admin console (standard sidebar-panel shell,
every module a real page including a Configuration screen for all five
config groups, a popup-based Plans editor with the rich-text description
and reordering above, plus a "TEST MODE" badge shown whenever the backend
has it on) - see `frontend/README.md`.
See **[docs/implementation-status.md](docs/implementation-status.md)**
for the exact done/not-done breakdown and suggested next steps - read that
before assuming any given feature works.

## Architecture

Modular monolith: FastAPI + SQLAlchemy + Alembic + MySQL backend (switched
from PostgreSQL 2026-09-13 - see docs/implementation-status.md for the
full rationale and what changed), React + TypeScript + Vite frontend
(`frontend/` - corrected from Angular on 2026-08-27, scaffolded and built
in increment 3), Celery/Redis for background jobs. See `backend/app/`
for the module layout (customers, plans, subscriptions, payments,
invoices, notifications, webhooks, integrations, sso, audit, auth [admin
auth + customer OTP], admin/customer/public API routers).

## Local development

### Option A: bare Python + your own MySQL

Any MySQL 8.0+ works - a XAMPP install, a standalone `mysqld`, or a
managed cloud instance. Create the database and a user for the app first
(skip this if you're just pointing at XAMPP's default `root` user):

```sql
CREATE DATABASE subscription CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'subscription'@'localhost' IDENTIFIED BY 'subscription';
GRANT ALL PRIVILEGES ON subscription.* TO 'subscription'@'localhost';
FLUSH PRIVILEGES;
```

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then edit DATABASE_URL etc. if needed
export DATABASE_URL="mysql+pymysql://subscription:subscription@localhost:3306/subscription?charset=utf8mb4"
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

Using XAMPP's bundled MySQL instead: its default is user `root` with no
password, so `DATABASE_URL` is usually
`mysql+pymysql://root:@localhost:3306/subscription?charset=utf8mb4` -
just create the `subscription` database first (in phpMyAdmin, or the
`CREATE DATABASE ...` line above via XAMPP's "Shell" button).

`python -m app.core.seed` prints the dev admin login
(`admin@example.com` / `ChangeMe123!`) and its MFA secret/provisioning
URI to stdout - use those, or submit `"BYPASS"` as the MFA code, against
`POST /api/v1/admin/auth/login` then `POST /api/v1/admin/auth/mfa/verify`.
To keep a specific admin login across a fresh database instead of the
dev default, set `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` in
your `.env` before running the seed script (see app/core/config.py) -
neither value is ever printed or logged.

API docs: http://localhost:8000/docs (Swagger) or /redoc.

### Option A2: MySQL via Docker instead of installing it locally

If you'd rather not install MySQL directly, run just the database in a
container and still run the backend itself with plain Python as above:

```bash
docker run -d --name subscription-mysql \
  -e MYSQL_DATABASE=subscription \
  -e MYSQL_USER=subscription \
  -e MYSQL_PASSWORD=subscription \
  -e MYSQL_ROOT_PASSWORD=root-change-me \
  -p 3306:3306 \
  mysql:8.0
```

Then use the same `DATABASE_URL` as Option A
(`mysql+pymysql://subscription:subscription@localhost:3306/subscription?charset=utf8mb4`)
and continue with `alembic upgrade head` etc. above.

### Option B: Docker Compose (backend + frontend)

The root `docker-compose.yml` brings up two app containers - `backend`
(the API) and `frontend` (the built React app, served by nginx inside
the container) - plus `redis`, `worker`, and `scheduler` (the latter two
are Celery processes backend needs, not optional extras - see the file's
own header comment). MySQL and the reverse proxy in front of these two
ports are NOT part of this file - both are already installed directly
on the host in this deployment; see the compose file's header comment
and `backend/.env.example`'s `DATABASE_URL` section for the
`host.docker.internal` + MySQL grant/bind-address setup that requires.

Two separate `.env` files, for two different reasons (see each
`.env.example`'s own comment for why they can't be merged):

```bash
cp .env.example .env                     # compose-level only: VITE_API_BASE_URL build arg
cp backend/.env.example backend/.env     # backend runtime secrets/config
# fill in both, then:
docker compose up --build -d
docker compose run --rm seed             # first time only: seed plans/admin user
```

Backend API docs once it's up: http://localhost:8002/docs (Swagger) or
/redoc. Frontend: http://localhost:3000. Point your host nginx's
`proxy_pass` at whichever of these two ports each of its routes should
reach - that reverse-proxy config isn't part of this repo.

#### Local testing with the same single-origin routing as production

`docker-compose.local.yml` adds a *containerized* nginx (local-only -
production uses your host's own nginx instead) so you can test the
exact same one-domain, path-routed shape locally: the browser talks to
one origin, nginx sends `/api/*` to `backend` and everything else to
`frontend`. This also means frontend and API become the same origin
locally, so CORS never enters into testing that path.

```bash
cp .env.example .env
# then set VITE_API_BASE_URL=http://localhost:8080 in that .env (NOT
# :8002 - see nginx.local.conf's header comment for why), then:
cp backend/.env.example backend/.env
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
```

Open http://localhost:8080 - that one port now serves everything, the
same way `https://plans.everyticket.in` will in production.

### Frontend (without Docker)

```bash
cd frontend
npm install
cp .env.example .env   # adjust VITE_API_BASE_URL if the backend isn't on :8002
npm run dev
```

Needs the backend running first, and the backend's `CORS_ORIGINS` to
include whatever origin the frontend actually opens at (default covers
`http://localhost:5173`). See `frontend/README.md` for what's covered.

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
| Run worker | `celery -A app.core.celery_app worker --loglevel=info` |
| Run scheduler (beat) | `celery -A app.core.celery_app beat --loglevel=info` |

**Both the worker and the beat scheduler must be running** (alongside
Redis and the backend) for any real, automatic webhook dispatch to ever
happen - `app.webhooks.service.dispatch_pending` (the function that
actually makes the outbound HTTP POST to Everyticket for a queued
delivery) is only ever invoked by the `dispatch-pending-webhooks` beat
schedule entry in `app/core/celery_app.py`, which fires every 60
seconds. If only `uvicorn` is running (Option A above, without also
starting these two processes in separate terminals), queued deliveries
will sit at `PENDING` with no `http_status`/`response_body` forever -
not because anything failed, but because they were never actually
attempted. The admin Webhook Logs screen's "Attempt" button sidesteps
this by making the real HTTP call immediately and synchronously from
the request itself (the same way "Verify connectivity" already does),
which is the quickest way to get a real result for one specific
delivery without starting Celery at all - but the worker + beat
processes above are still what's needed for dispatch to happen
automatically, without an admin manually clicking Attempt every time.

## Documentation

- [docs/implementation-status.md](docs/implementation-status.md) - what's
  built vs. spec, and the suggested order for continuing.

## Environment variables

See `backend/.env.example` for the full backend config list with
comments, and the root `.env.example` for the one Docker-Compose-level
variable (`VITE_API_BASE_URL`) - see that file's own comment for why
it's separate. Never commit a real `.env` file - both are gitignored.
