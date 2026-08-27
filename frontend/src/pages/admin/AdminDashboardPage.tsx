/**
 * Deliberately minimal: the backend has no admin CRUD API yet beyond
 * login/me (see docs/implementation-status.md - plans/customers/
 * subscriptions/payments/invoices/webhook-logs/audit-logs admin
 * endpoints are still on the roadmap), so there's nothing further to
 * build here until that surface exists. This confirms the admin session
 * works and gives a clear "nothing here yet" rather than a broken page.
 */
import { useEffect, useState } from "react";
import { getAdminMe } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";
import type { AdminUserOut } from "../../api/types";

export function AdminDashboardPage() {
  const { adminToken, setAdminToken } = useAuth();
  const [me, setMe] = useState<AdminUserOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    getAdminMe(adminToken).then(setMe).catch(setError);
  }, [adminToken]);

  return (
    <section>
      <div className="page-header-row">
        <h1>Admin</h1>
        <button className="button button-secondary" onClick={() => setAdminToken(null)}>
          Sign out
        </button>
      </div>

      <ErrorBanner error={error} />

      {me && (
        <div className="card">
          <dl className="summary-list">
            <dt>Email</dt>
            <dd>{me.email}</dd>
            <dt>Name</dt>
            <dd>{me.full_name}</dd>
            <dt>Roles</dt>
            <dd>{me.roles.join(", ") || "-"}</dd>
            <dt>MFA</dt>
            <dd>{me.mfa_enabled ? "Enabled" : "Disabled"}</dd>
          </dl>
        </div>
      )}

      <div className="card">
        <p className="hint">
          There's no admin management API yet (plans, customers, subscriptions, payments, invoices,
          webhook/audit logs) - this page just confirms your admin session works. See
          docs/implementation-status.md for what's planned next.
        </p>
      </div>
    </section>
  );
}
