/**
 * Two independent auth states - customer and admin - since a browser
 * could plausibly have both a customer session and an admin session open
 * (e.g. an admin testing the customer flow). Each token is a JWT the
 * backend issues with a distinct `token_kind` claim (see
 * backend/app/core/security.py); the frontend never inspects the token's
 * contents, just stores and forwards it.
 *
 * Persisted to localStorage so a page refresh doesn't force a re-login -
 * this is a real browser app the user runs with `npm run dev`/deploys
 * standalone, not an embedded preview, so localStorage is the right tool
 * here (unlike a Claude-artifact page, which can't rely on it).
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

const CUSTOMER_TOKEN_KEY = "subscription.customerToken";
const ADMIN_TOKEN_KEY = "subscription.adminToken";

interface AuthContextValue {
  customerToken: string | null;
  setCustomerToken: (token: string | null) => void;
  adminToken: string | null;
  setAdminToken: (token: string | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredToken(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    // Private browsing / storage disabled - fall back to in-memory-only
    // for this session rather than crashing the app.
    return null;
  }
}

function writeStoredToken(key: string, token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem(key, token);
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Same as above - non-fatal if storage isn't available.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [customerToken, setCustomerTokenState] = useState<string | null>(() =>
    readStoredToken(CUSTOMER_TOKEN_KEY),
  );
  const [adminToken, setAdminTokenState] = useState<string | null>(() => readStoredToken(ADMIN_TOKEN_KEY));

  const setCustomerToken = useCallback((token: string | null) => {
    writeStoredToken(CUSTOMER_TOKEN_KEY, token);
    setCustomerTokenState(token);
  }, []);

  const setAdminToken = useCallback((token: string | null) => {
    writeStoredToken(ADMIN_TOKEN_KEY, token);
    setAdminTokenState(token);
  }, []);

  const value = useMemo(
    () => ({ customerToken, setCustomerToken, adminToken, setAdminToken }),
    [customerToken, setCustomerToken, adminToken, setAdminToken],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
