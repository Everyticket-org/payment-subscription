/**
 * Everyticket SSO landing page (spec section 47). Everyticket redirects
 * the customer's browser here with ?token=<signed token>; this page's
 * only job is to redeem it against POST /public/sso/consume and drop the
 * resulting customer session into AuthContext, then continue on to the
 * portal exactly as a normal OTP-verified login would. A TEST_MODE admin
 * "Generate test SSO link" action (see AdminCustomerDetailPage) points
 * here too, since there's no real Everyticket instance in this build.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { consumeSsoToken } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";

export function SsoConsumePage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const { setCustomerToken } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    if (!token) {
      setError({ message: "No SSO token was provided in the link." });
      return;
    }

    consumeSsoToken(token)
      .then((result) => {
        setCustomerToken(result.access_token);
        navigate("/portal", { replace: true });
      })
      .catch(setError);
  }, [token, setCustomerToken, navigate]);

  return (
    <section>
      <h1>Signing you in...</h1>
      <ErrorBanner error={error} />
      {!error && <p>Please wait while we verify your Everyticket sign-in link.</p>}
    </section>
  );
}
