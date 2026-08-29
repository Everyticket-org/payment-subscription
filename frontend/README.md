# Everyticket Subscriptions - frontend

React + TypeScript + Vite. Covers the public plan/subscribe flow, customer OTP login + portal
(view subscription, upgrade/downgrade/renew/cancel), and a full admin console: login (password +
MFA), a real dashboard, and CRUD/read-only screens for plans, customers, subscriptions, payments,
invoices, webhook logs, notification templates/logs, and audit logs. See
`docs/implementation-status.md` at the repo root for what's built vs. still spec - the
Testing/Developer Tools admin module and the dynamic registration-form renderer are the main
frontend gaps left.

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

- No real payment gateway is wired up in the backend yet (Mock only) - every place a payment is
  required (subscribe, upgrade, downgrade, renew) shows a "simulate payment success/failure"
  action instead of a real checkout, calling the same mock-callback endpoint a real gateway
  webhook will eventually use.
- Customer auth token and admin auth token are both kept in `localStorage` (see
  `src/context/AuthContext.tsx`) - this is a real standalone app the user runs in their own
  browser, not an embedded preview, so that's the normal, correct place for them.
- There's no dynamic registration-form renderer yet (spec section 8) - `registration_data` is
  sent as `{}` on subscribe.
