/**
 * Detects "your session is no longer valid" specifically - the backend's
 * Unauthorized exception (app/core/exceptions.py), returned as HTTP 401
 * with error_code "UNAUTHORIZED" whenever a bearer token is missing,
 * malformed, or expired (see app/core/security.py's decode_token).
 *
 * Deliberately narrower than "any 401": OTP verification (401
 * OTP_INVALID_OR_EXPIRED) and other auth-adjacent failures use their own
 * error codes and should keep showing their normal inline error instead
 * of being treated as a dead session.
 *
 * Callers that get true back should clear the stored token (see
 * useAuth().setCustomerToken/setAdminToken) rather than just displaying
 * the error - RequireCustomer/RequireAdmin (components/ProtectedRoute.tsx)
 * only check whether a token is present, not whether it's still valid, so
 * a page that just shows the raw error and leaves the stale token in
 * place strands the user: every retry fails the same way, and any
 * page-level "Sign out" control lives inside content that never renders
 * because the same failed fetch is what would have unlocked it.
 */
import { ApiError } from "../api/client";

export function isSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401 && error.errorCode === "UNAUTHORIZED";
}
