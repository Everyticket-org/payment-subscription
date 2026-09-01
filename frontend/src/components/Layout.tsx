import { Link, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import logoUrl from "../assets/logo.svg";

// Real Everyticket logo, bundled locally (src/assets/logo.svg) rather
// than loaded from their site, so this page never depends on an
// external host being reachable. Swaps out the old text wordmark. Admin
// is deliberately no longer linked from here (still reachable directly
// at /admin/login for anyone who knows the URL) - this header is
// customer-facing only.

export function Layout() {
  const { customerToken } = useAuth();

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="brand">
          <img src={logoUrl} alt="Everyticket" className="brand-logo" />
        </Link>
        <nav>
          <Link to="/">Plans</Link>
          <Link to={customerToken ? "/portal" : "/login"}>My Subscriptions</Link>
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
