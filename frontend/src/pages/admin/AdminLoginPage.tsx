/**
 * Two-step admin login: password -> pre_mfa_token -> MFA code -> tokens
 * (see backend/app/auth/service.py). The "BYPASS" hint below is just
 * that - a hint; whether it's actually accepted is enforced entirely
 * server-side (ALLOW_ADMIN_MFA_BYPASS + non-production), so this button
 * is harmless to show even in an environment where it'll be rejected.
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { adminLogin, adminVerifyMfa } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";

export function AdminLoginPage() {
  const { setAdminToken } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [preMfaToken, setPreMfaToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await adminLogin(email, password);
      if (result.mfa_required && result.pre_mfa_token) {
        setPreMfaToken(result.pre_mfa_token);
      } else if (result.access_token) {
        setAdminToken(result.access_token);
        navigate("/admin");
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleMfa(e: FormEvent) {
    e.preventDefault();
    if (!preMfaToken) return;
    setBusy(true);
    setError(null);
    try {
      const result = await adminVerifyMfa(preMfaToken, mfaCode);
      setAdminToken(result.access_token);
      navigate("/admin");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-page">
      <h1>Admin sign in</h1>
      <ErrorBanner error={error} />

      {!preMfaToken ? (
        <form className="card" onSubmit={handleLogin}>
          <label>
            Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Password
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <button className="button button-primary" type="submit" disabled={busy}>
            {busy ? "Signing in..." : "Sign in"}
          </button>
        </form>
      ) : (
        <form className="card" onSubmit={handleMfa}>
          <p>Enter your authenticator app code.</p>
          <p className="hint hint-dev">
            Dev/staging only: submitting <code>BYPASS</code> as the code skips MFA if the backend has it
            enabled for this environment.
          </p>
          <label>
            MFA code
            <input type="text" required value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} />
          </label>
          <button className="button button-primary" type="submit" disabled={busy}>
            {busy ? "Verifying..." : "Verify"}
          </button>
        </form>
      )}
    </section>
  );
}
