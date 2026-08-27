import { Link, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function Layout() {
  const { customerToken, adminToken } = useAuth();

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="brand">
          Everyticket Subscriptions
        </Link>
        <nav>
          <Link to="/">Plans</Link>
          {customerToken ? <Link to="/portal">My account</Link> : <Link to="/login">Sign in</Link>}
          {adminToken ? <Link to="/admin">Admin</Link> : <Link to="/admin/login">Admin</Link>}
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
