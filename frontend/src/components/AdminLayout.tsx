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
import logoUrl from "../assets/logo.svg";

type NavItem = { label: string; path: string };
type NavGroup = { label: string; items: NavItem[] };

const DASHBOARD: NavItem = { label: "Dashboard", path: "/admin" };

// Grouped into categories + submenus (previously one flat 12-item list) -
// each group's items share a real functional area rather than just
// following router-registration order.
const NAV_GROUPS: NavGroup[] = [
  {
    label: "Catalog",
    items: [
      { label: "Plans", path: "/admin/plans" },
      { label: "Registration form", path: "/admin/registration-form" },
    ],
  },
  {
    label: "Customers",
    items: [
      { label: "Customers", path: "/admin/customers" },
      { label: "Subscriptions", path: "/admin/subscriptions" },
    ],
  },
  {
    label: "Billing",
    items: [
      { label: "Payments", path: "/admin/payments" },
      { label: "Invoices", path: "/admin/invoices" },
    ],
  },
  {
    label: "Communications",
    items: [
      { label: "Notifications", path: "/admin/notifications" },
      { label: "Webhook logs", path: "/admin/webhooks" },
    ],
  },
  {
    label: "System",
    items: [
      { label: "Audit logs", path: "/admin/audit" },
      { label: "Testing tools", path: "/admin/testing" },
    ],
  },
  // 2026-09-14 follow-up: "Under Configuration, 4 sub menu will come - 1.
  // General... 2. Payment Gateway... 3. Communication... 4. Integration"
  // - Configuration is now its own sidebar group (like Catalog/Customers/
  // Billing above) instead of a single item buried in System, with one
  // route per section (see App.tsx) instead of one long stacked page.
  {
    label: "Configuration",
    items: [
      { label: "General", path: "/admin/config/general" },
      { label: "Payment Gateway", path: "/admin/config/payment-gateway" },
      { label: "Communication", path: "/admin/config/communication" },
      { label: "Integration", path: "/admin/config/integration" },
    ],
  },
];

function isActivePath(pathname: string, itemPath: string): boolean {
  return itemPath === "/admin" ? pathname === itemPath : pathname.startsWith(itemPath);
}

export function AdminLayout() {
  const { adminToken, setAdminToken } = useAuth();
  const location = useLocation();
  const [testMode, setTestMode] = useState(false);
  // Whichever group holds the current route starts expanded; the rest
  // start collapsed so the sidebar isn't just the old flat list again.
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      NAV_GROUPS.map((group) => [
        group.label,
        group.items.some((item) => isActivePath(location.pathname, item.path)),
      ]),
    ),
  );

  useEffect(() => {
    if (!adminToken) return;
    getTestModeStatus(adminToken)
      .then((status) => setTestMode(status.test_mode))
      .catch(() => setTestMode(false));
  }, [adminToken]);

  function toggleGroup(label: string) {
    setOpenGroups((prev) => ({ ...prev, [label]: !prev[label] }));
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <Link to="/admin" className="admin-brand">
          <img src={logoUrl} alt="Everyticket" className="admin-brand-logo" />
        </Link>
        <nav className="admin-nav">
          <Link
            to={DASHBOARD.path}
            className={"admin-nav-link" + (isActivePath(location.pathname, DASHBOARD.path) ? " active" : "")}
          >
            {DASHBOARD.label}
          </Link>

          {NAV_GROUPS.map((group) => {
            const open = openGroups[group.label] ?? false;
            return (
              <div className="admin-nav-group" key={group.label}>
                <button
                  type="button"
                  className="admin-nav-group-header"
                  onClick={() => toggleGroup(group.label)}
                  aria-expanded={open}
                >
                  <span>{group.label}</span>
                  <span className={"admin-nav-caret" + (open ? " open" : "")}>&#x25BE;</span>
                </button>
                {open && (
                  <div className="admin-nav-submenu">
                    {group.items.map((item) => (
                      <Link
                        key={item.path}
                        to={item.path}
                        className={
                          "admin-nav-link admin-nav-sublink" +
                          (isActivePath(location.pathname, item.path) ? " active" : "")
                        }
                      >
                        {item.label}
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
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
