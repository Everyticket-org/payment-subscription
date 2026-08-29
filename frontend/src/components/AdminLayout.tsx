/**
 * Standard admin-panel chrome: fixed sidebar nav + topbar, replacing the
 * public site's header/footer entirely for everything under /admin
 * (spec sections 12, 51-53). Only "Dashboard" is a real page today -
 * Plans/Customers/Subscriptions/Payments/Invoices/Webhook Logs/Audit Logs
 * are listed and disabled rather than hidden, so the shell communicates
 * the intended admin surface even before docs/implementation-status.md's
 * admin CRUD API exists to back them (see that file for the current
 * status of each).
 */
import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const NAV_ITEMS: Array<{ label: string; path: string; enabled: boolean }> = [
  { label: "Dashboard", path: "/admin", enabled: true },
  { label: "Plans", path: "/admin/plans", enabled: false },
  { label: "Customers", path: "/admin/customers", enabled: false },
  { label: "Subscriptions", path: "/admin/subscriptions", enabled: false },
  { label: "Payments", path: "/admin/payments", enabled: false },
  { label: "Invoices", path: "/admin/invoices", enabled: false },
  { label: "Webhook logs", path: "/admin/webhooks", enabled: false },
  { label: "Audit logs", path: "/admin/audit", enabled: false },
];

export function AdminLayout() {
  const { adminToken, setAdminToken } = useAuth();
  const location = useLocation();

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
                className={"admin-nav-link" + (location.pathname === item.path ? " active" : "")}
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
