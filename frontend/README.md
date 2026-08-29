# Everyticket Subscriptions - frontend

React + TypeScript + Vite. Covers the public plan/subscribe flow (with a dynamic
per-application registration form; mock simulate buttons or a real PayU checkout redirect,
depending on the application's configured gateway), customer OTP login + portal (view
subscription incl. its provisioning status, upgrade/downgrade/renew/cancel) + an Everyticket SSO
landing page, and a full admin console: login (password + MFA), a real dashboard, CRUD/read-only
screens for plans, customers, subscriptions, payments, invoices, webhook logs, notification
templates/logs, audit logs, and registration-form fields (plus a "Generate test SSO link" action
on the customer detail page), a Configuration page (Payment Gateway, Everyticket Integration,
Notification, Subscription Rules, and Security config - each screen backed by real enforcement,
not just storage), a Testing/Developer Tools page (test payment simulation, test subscription
events, a live webhook sender, a webhook failure/retry simulator, test email sending, OTP/MFA
bypass toggles, and a test-data generator + cleanup) with a "TEST MODE" badge shown in the admin
topbar whenever the backend has it on, and a GST/tax configuration panel on the Invoices page
plus PDF download/email-resend actions on the invoice detail page (also downloadable from the
customer portal's own invoice list). See `docs/implementation-status.md` at the repo root for
what's built vs. still spec.

## Local development

```bash
npm install
cp .env.example .env   # adjust VITE_API_BASE_URL if your backend isn't on the default port
npm run dev
```

Requires the backend running separately (see `backend/README.md` at the repo root) - by default
this expects it at `http://localhost:8000`.

**CORS**: the backend only accepts browser requests from origins listed in its `CORS_ORIGINS`
setting (default covers `http://localhost:5173` and `http://127.0.0.1:5173` - Vite's default dev
port, both hostname spellings since browsers treat them as different origins). If you run the
frontend on a different port, add it to the backend's `CORS_ORIGINS` too or requests will fail
with a CORS error before ever reaching the API.

## Build

```bash
npm run build    # tsc -b && vite build - output in dist/
npm run preview  # serve the production build locally to sanity-check it
```

## Notes

- Which payment flow renders (mock "simulate success/failure" buttons vs. a real PayU
  hosted-checkout redirect) is driven entirely by the application's configured
  `default_gateway` (Admin > Configuration > Payment Gateway) - both call through the same
  subscribe/upgrade/downgrade/renew endpoints.
- Customer auth token and admin auth token are both kept in `localStorage` (see
  `src/context/AuthContext.tsx`) - this is a real standalone app the user runs in their own
  browser, not an embedded preview, so that's the normal, correct place for them.
