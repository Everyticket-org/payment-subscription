import { useEffect, useState, type ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { getCustomerPortal } from "../api/endpoints";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { isSessionExpired } from "../utils/authError";

export function RequireCustomer({ children }: { children: ReactNode }) {
  const { customerToken } = useAuth();
  if (!customerToken) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { adminToken } = useAuth();
  if (!adminToken) {
    return <Navigate to="/admin/login" replace />;
  }
  return <>{children}</>;
}

/**
 * Guards the public Plans page (spec follow-up, 2026-09-13: "After login,
 * If user has already subscription then it should not allow to go to
 * Plans page - it should go to my subscription page and ask for change
 * plan"). A signed-in customer who already has an active, non-trial
 * subscription gets redirected to /portal instead of ever seeing the
 * plan grid - "Change plan" (already on PortalPage, spec's proper path
 * for switching plans) is what they should use, not re-running the
 * new-subscription flow.
 *
 * Deliberately scoped to non-trial subscriptions only: PortalPage already
 * refuses to offer "Change plan" for a trial (a trial can't be switched
 * to another plan - see its "Free trials can't be switched..." hint), so
 * a trial customer's ONLY path to a paid plan is this same Plans page.
 * Blocking them here would strand them with no way to ever pay.
 *
 * A signed-out visitor (no customerToken) always passes straight through
 * - this only ever redirects an authenticated customer away from Plans,
 * never blocks a new visitor from seeing them.
 *
 * This is a UX guard only, not a security boundary: a signed-in customer
 * who instead navigates straight to /subscribe/:planCode bypasses it, but
 * that's unchanged and safe - the backend already auto-routes an
 * already-subscribed customer's /subscribe call to upgrade/downgrade
 * against their existing subscription rather than creating a duplicate
 * (spec section 9/22), so nothing relies on this guard for correctness.
 */
export function RedirectIfActiveSubscription({ children }: { children: ReactNode }) {
  const { customerToken, setCustomerToken } = useAuth();
  const toast = useToast();
  const [status, setStatus] = useState<"checking" | "allow" | "redirect">(customerToken ? "checking" : "allow");

  useEffect(() => {
    if (!customerToken) {
      setStatus("allow");
      return;
    }
    let cancelled = false;
    setStatus("checking");
    getCustomerPortal(customerToken)
      .then((portal) => {
        if (cancelled) return;
        if (portal.active_subscription && !portal.active_subscription.is_trial) {
          toast.info("You already have an active subscription - use Change plan below to switch.");
          setStatus("redirect");
        } else {
          setStatus("allow");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        // An expired/invalid token shouldn't block access to the public
        // Plans page - clear it (same "dead session" handling every
        // other customer page uses) and let them browse as a signed-out
        // visitor. Any other failure fails open too: this is a UX nicety,
        // not something worth turning into a dead end.
        if (isSessionExpired(err)) {
          setCustomerToken(null);
        }
        setStatus("allow");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- toast/setCustomerToken are stable from context
  }, [customerToken]);

  if (status === "checking") {
    return null;
  }
  if (status === "redirect") {
    return <Navigate to="/portal" replace />;
  }
  return <>{children}</>;
}
