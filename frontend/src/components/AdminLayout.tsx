/**
 * Standard admin-panel chrome: fixed sidebar nav + topbar, replacing the
 * public site's header/footer entirely for everything under /admin
 * (spec sections 12, 51-53). Every module below is backed by a real
 * admin_*.py API router (see docs/implementation-status.md). Also shows
 * a prominent "TEST MODE" badge in the topbar whenever the backend
 * reports TEST_MODE is on (spec section 55: "Display TEST MODE
 * prominently in development/staging").
 */
import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { getTestModeStatus } from "../api/endpoints";
import { useAuth } from "../context/AuthContext";

const NAV_ITEMS: Array<{ label: string; path: string; enabled: boolean }> = [
  { label: "Dashboard", path: "/admin", enabled: true },
  { label: "Plans", path: "/admin/plans", enabled: true },
  { label: "Registration form", path: "/admin/registration-form", enabled: true },
  { label: "Customers", path: "/admin/customers", enabled: true },
  { label: "Subscriptions", path: "/admin/subscriptions", enabled: true },
  { label: "Payments", path: "/admin/payments", enabled: true },
  { label: "Invoices", path: "/admin/invoices", enabled: true },
  { label: "Webhook logs", path: "/admin/webhooks", enabled: true },
  { label: "Notifications", path: "/admin/notifications", enabled: true },
  { label: "Audit logs", path: "/admin/audit", enabled: true },
  { label: "Testing tools", path: "/admin/testing", enabled: true },
  { label: "Configuration", path: "/admin/config", enabled: true },
];

export function AdminLayout() {
  const { adminToken, setAdminToken } = useAuth();
  const location = useLocation();
  const [testMode, setTestMode] = useState(false);

  useEffect(() => {
    if (!adminToken) return;
    getTestModeStatus(adminToken)
      .then((status) => setTestMode(status.test_mode))
      .catch(() => setTestMode(false));
  }, [adminToken]);

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <Link to="/admin" className="admin-brand">
          Everyticket <span>Admin</span>
        </Link>
        <nav className="admin-nav">
          {NAV_ITEMS.map((item) =>
            item.enabled ? (
              <Link
                key={item.path}
                to={item.path}
                className={
                  "admin-nav-link" +
                  ((item.path === "/admin" ? location.pathname === item.path : location.pathname.startsWith(item.path))
                    ? " active"
                    : "")
                }
              >
                {item.label}
              </Link>
            ) : (
              <span key={item.path} className="admin-nav-link disabled" title="Not built yet">
                {item.label}
                <span className="admin-nav-badge">soon</span>
              </span>
            ),
          )}
        </nav>
        <Link to="/" className="admin-nav-link admin-nav-exit">
          &larr; Back to public site
        </Link>
      </aside>
      <div className="admin-main">
        <header className="admin-topbar">
          <span className="admin-topbar-title">Admin console</span>
          {testMode && <span className="badge badge-warning">TEST MODE</span>}
          {adminToken && (
            <button className="button button-secondary" onClick={() => setAdminToken(null)}>
              Sign out
            </button>
          )}
        </header>
        <main className="admin-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
