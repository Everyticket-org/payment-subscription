/**
 * Standard admin-panel chrome: fixed sidebar nav + topbar, replacing the
 * public site's header/footer entirely for everything under /admin
 * (spec sections 12, 51-53). Every module below is backed by a real
 * admin_*.py API router (see docs/implementation-status.md). Also shows
 * a prominent "TEST MODE" badge in the topbar whenever the backend
 * reports TEST_MODE is on (spec section 55: "Display TEST MODE
 * prominently in development/staging").
 *
 * 2026-09-15 follow-up ("suggest better design of admin panel... Now
 * sidebar menu"): sidebar restyled per the approved mockup - icons on
 * Dashboard and every nav group, a gradient sidebar background, and a
 * real admin-identity footer (avatar/name/email from GET /admin/me,
 * not the mockup's placeholder "Admin User" text) with a working
 * sign-out action. Routing/active-state logic and every existing nav
 * item/path are unchanged - this is a chrome-only restyle.
 */
import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { getAdminMe, getTestModeStatus } from "../api/endpoints";
import { useAuth } from "../context/AuthContext";
import logoUrl from "../assets/logo.svg";

type NavItem = { label: string; path: string };
type NavGroup = { label: string; icon: IconName; items: NavItem[] };

const DASHBOARD: NavItem = { label: "Dashboard", path: "/admin" };

// Grouped into categories + submenus (previously one flat 12-item list) -
// each group's items share a real functional area rather than just
// following router-registration order.
const NAV_GROUPS: NavGroup[] = [
  {
    label: "Catalog",
    icon: "tag",
    items: [
      { label: "Plans", path: "/admin/plans" },
      { label: "Registration form", path: "/admin/registration-form" },
    ],
  },
  {
    label: "Customers",
    icon: "users",
    items: [
      { label: "Customers", path: "/admin/customers" },
      { label: "Subscriptions", path: "/admin/subscriptions" },
    ],
  },
  {
    label: "Billing",
    icon: "billing",
    items: [
      { label: "Payments", path: "/admin/payments" },
      { label: "Invoices", path: "/admin/invoices" },
    ],
  },
  {
    label: "Communications",
    icon: "comms",
    items: [
      { label: "Notifications", path: "/admin/notifications" },
      { label: "Webhook logs", path: "/admin/webhooks" },
    ],
  },
  {
    label: "System",
    icon: "system",
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
    icon: "config",
    items: [
      { label: "General", path: "/admin/config/general" },
      { label: "Payment Gateway", path: "/admin/config/payment-gateway" },
      { label: "Communication", path: "/admin/config/communication" },
      { label: "Integration", path: "/admin/config/integration" },
    ],
  },
];

// ---- Sidebar icons (2026-09-15 sidebar redesign) - one small inline SVG
// per nav group plus Dashboard/sign-out, same viewBox/stroke convention
// SubscribePage.tsx's CardIcon/CheckCircleIcon already established. Kept
// here (not a shared icons module) since nothing else in the app uses
// this exact icon set yet. ----
type IconName = "dashboard" | "tag" | "users" | "billing" | "comms" | "system" | "config";

function NavIcon({ name }: { name: IconName }) {
  const paths = {
    dashboard: (
      <>
        <path d="M4 4h7v7H4V4zm9 0h7v4h-7V4zm0 7h7v9h-7v-9zM4 14h7v6H4v-6z" />
      </>
    ),
    tag: (
      <>
        <path d="M3 11.5V4a1 1 0 0 1 1-1h7.5a1 1 0 0 1 .7.3l8 8a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0l-8-8a1 1 0 0 1-.3-.7z" />
        <circle cx="7.5" cy="7.5" r="1.5" />
      </>
    ),
    users: (
      <>
        <path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
        <circle cx="10" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </>
    ),
    billing: (
      <>
        <rect x="2" y="5" width="20" height="14" rx="2.5" />
        <path d="M2 10h20" />
        <path d="M6 15h4" />
      </>
    ),
    comms: (
      <>
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.7 21a2 2 0 0 1-3.4 0" />
      </>
    ),
    system: (
      <>
        <circle cx="12" cy="12" r="3.2" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.9-2.9l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.9-2.9l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.6V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.9 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.6 1H21a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.6 1z" />
      </>
    ),
    config: (
      <>
        <line x1="4" y1="6" x2="20" y2="6" />
        <circle cx="9" cy="6" r="2" />
        <line x1="4" y1="12" x2="20" y2="12" />
        <circle cx="16" cy="12" r="2" />
        <line x1="4" y1="18" x2="20" y2="18" />
        <circle cx="10" cy="18" r="2" />
      </>
    ),
  };
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}

function SignOutIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  );
}

function isActivePath(pathname: string, itemPath: string): boolean {
  return itemPath === "/admin" ? pathname === itemPath : pathname.startsWith(itemPath);
}

/** First letter of up to the first two words of a name, e.g. "Everyticket
 * Admin" -> "EA" - used for the sidebar footer's avatar when there's a
 * real admin identity to show. */
function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

export function AdminLayout() {
  const { adminToken, setAdminToken } = useAuth();
  const location = useLocation();
  const [testMode, setTestMode] = useState(false);
  const [adminIdentity, setAdminIdentity] = useState<{ full_name: string; email: string } | null>(null);
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
    getAdminMe(adminToken)
      .then((me) => setAdminIdentity({ full_name: me.full_name, email: me.email }))
      .catch(() => setAdminIdentity(null));
  }, [adminToken]);

  function toggleGroup(label: string) {
    setOpenGroups((prev) => ({ ...prev, [label]: !prev[label] }));
  }

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <Link to="/admin" className="admin-brand">
          <img src={logoUrl} alt="Everyticket" className="admin-brand-logo" />
          <span className="admin-brand-caption">Admin console</span>
        </Link>
        <nav className="admin-nav">
          <Link
            to={DASHBOARD.path}
            className={"admin-nav-link" + (isActivePath(location.pathname, DASHBOARD.path) ? " active" : "")}
          >
            <NavIcon name="dashboard" />
            <span>{DASHBOARD.label}</span>
          </Link>

          {NAV_GROUPS.map((group) => {
            const open = openGroups[group.label] ?? false;
            return (
              <div className="admin-nav-group" key={group.label}>
                <button
                  type="button"
                  className="admin-nav-link admin-nav-group-header"
                  onClick={() => toggleGroup(group.label)}
                  aria-expanded={open}
                >
                  <NavIcon name={group.icon} />
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

        {adminIdentity && (
          <div className="admin-sidebar-footer">
            <span className="admin-avatar" aria-hidden="true">
              {initialsFor(adminIdentity.full_name)}
            </span>
            <span className="admin-sidebar-who">
              <b>{adminIdentity.full_name}</b>
              <span>{adminIdentity.email}</span>
            </span>
            <button
              type="button"
              className="admin-sidebar-signout"
              title="Sign out"
              aria-label="Sign out"
              onClick={() => setAdminToken(null)}
            >
              <SignOutIcon />
            </button>
          </div>
        )}
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
