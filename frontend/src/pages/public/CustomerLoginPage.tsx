/**
 * Standalone customer sign-in: identify -> OTP verify, for someone who
 * already has an account and just wants to reach their portal (as
 * opposed to the same flow inlined into SubscribePage for a new
 * purchase). There's no separate "direct OTP login" backend endpoint
 * (spec section 48) yet - this reuses /identify + /otp/verify, which
 * only issues a session when match_status is "exact".
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { identify, verifyOtp } from "../../api/endpoints";
import { ApiError } from "../../api/client";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";

export function CustomerLoginPage() {
  const { setCustomerToken } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [mobile, setMobile] = useState("");
  const [otpSessionId, setOtpSessionId] = useState<string | null>(null);
  const [debugOtpCode, setDebugOtpCode] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function handleIdentify(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await identify(email, mobile);
      if (result.match_status !== "exact") {
        setError(
          new ApiError(404, {
            error_code: "NO_ACCOUNT_FOUND",
            message:
              result.match_status === "conflict"
                ? "That email and mobile belong to different accounts - double check them, or subscribe to create a new account."
                : "No account found for that email/mobile. Subscribe to a plan to create one.",
          }),
        );
        return;
      }
      setOtpSessionId(result.otp_session_id);
      setDebugOtpCode(result.debug_otp_code);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    if (!otpSessionId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await verifyOtp(otpSessionId, otpCode);
      setCustomerToken(result.access_token);
      navigate("/portal");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="auth-page">
      <h1>Sign in</h1>
      <ErrorBanner error={error} />

      {!otpSessionId ? (
        <form className="card" onSubmit={handleIdentify}>
          <label>
            Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label>
            Mobile
            <input type="tel" required value={mobile} onChange={(e) => setMobile(e.target.value)} />
          </label>
          <button className="button button-primary" type="submit" disabled={busy}>
            {busy ? "Checking..." : "Continue"}
          </button>
        </form>
      ) : (
        <form className="card" onSubmit={handleVerify}>
          <p>Enter the verification code sent to your email/mobile.</p>
          {debugOtpCode && (
            <p className="hint hint-dev">
              Dev/test mode: the code is <code>{debugOtpCode}</code>.
            </p>
          )}
          <label>
            Verification code
            <input type="text" required value={otpCode} onChange={(e) => setOtpCode(e.target.value)} />
          </label>
          <button className="button button-primary" type="submit" disabled={busy}>
            {busy ? "Verifying..." : "Sign in"}
          </button>
        </form>
      )}
    </section>
  );
}
