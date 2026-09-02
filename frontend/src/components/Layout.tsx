import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import logoUrl from "../assets/logo.svg";

// Real Everyticket logo, bundled locally (src/assets/logo.svg) rather
// than loaded from their site, so this page never depends on an
// external host being reachable. Swaps out the old text wordmark. Admin
// is deliberately no longer linked from here (still reachable directly
// at /admin/login for anyone who knows the URL) - this header is
// customer-facing only.
//
// Sign out lives here, in the shell every customer page renders inside
// (see App.tsx), rather than only inside PortalPage's own content - a
// page that hasn't finished loading yet (or never will, e.g. an expired
// token that makes every fetch on it fail) still needs a working way
// out, and previously this header had none at all: the only "Sign out"
// button lived inside PortalPage's fully-loaded view, so a customer
// whose token expired mid-session got stuck on that page's error banner
// with no visible way to sign out (mirrors AdminLayout's topbar, which
// already gets this right for the admin console).

export function Layout() {
  const { customerToken, setCustomerToken } = useAuth();
  const navigate = useNavigate();

  function signOut() {
    setCustomerToken(null);
    navigate("/login");
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="brand">
          <img src={logoUrl} alt="Everyticket" className="brand-logo" />
        </Link>
        <nav>
          <Link to="/">Plans</Link>
          <Link to={customerToken ? "/portal" : "/login"}>My Subscriptions</Link>
          {customerToken && (
            <button type="button" className="app-header-signout" onClick={signOut}>
              Sign out
            </button>
          )}
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
      <footer className="app-footer">
        <span>Phase 1 build - see docs/implementation-status.md in the repo for what's real vs. still spec.</span>
      </footer>
    </div>
  );
}
