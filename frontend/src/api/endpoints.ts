/**
 * One function per backend endpoint this frontend uses. Keeping these
 * separate from client.ts's generic request logic means a page component
 * never constructs a URL path or knows an HTTP verb by hand.
 */
import { api } from "./client";
import type {
  AdminLoginResponse,
  AdminUserOut,
  CustomerPortalOut,
  IdentifyResponse,
  MockCallbackResult,
  OtpVerifyResponse,
  Plan,
  PortalSubscriptionOut,
  SubscribeResponse,
  TokenResponse,
} from "./types";

// --- Public ---

export const listPlans = () => api.get<Plan[]>("/api/v1/public/plans");

export const getPlan = (code: string) => api.get<Plan>(`/api/v1/public/plans/${code}`);

export const subscribe = (
  planCode: string,
  body: { email?: string; mobile?: string; registration_data?: Record<string, unknown> },
  customerToken?: string | null,
) => api.post<SubscribeResponse>(`/api/v1/public/plans/${planCode}/subscribe`, body, customerToken);

export const identify = (email: string, mobile: string) =>
  api.post<IdentifyResponse>("/api/v1/public/identify", { email, mobile });

export const verifyOtp = (otpSessionId: string, code: string) =>
  api.post<OtpVerifyResponse>("/api/v1/public/otp/verify", { otp_session_id: otpSessionId, code });

// --- Payment (mock gateway simulation) ---

export const simulateMockCallback = (transactionId: string, scenario: "SUCCESS" | "FAILED" | "PENDING" | "TIMEOUT") =>
  api.post<MockCallbackResult>("/api/v1/payment/mock/callback", { transaction_id: transactionId, scenario });

// --- Customer portal (requires customer bearer token) ---

export const getCustomerPortal = (token: string) => api.get<CustomerPortalOut>("/api/v1/customer/me", token);

export const upgradeSubscription = (subscriptionId: string, targetPlanCode: string, token: string) =>
  api.post<SubscribeResponse>(
    `/api/v1/customer/subscriptions/${subscriptionId}/upgrade`,
    { target_plan_code: targetPlanCode },
    token,
  );

export const downgradeSubscription = (subscriptionId: string, targetPlanCode: string, token: string) =>
  api.post<SubscribeResponse>(
    `/api/v1/customer/subscriptions/${subscriptionId}/downgrade`,
    { target_plan_code: targetPlanCode },
    token,
  );

export const renewSubscription = (subscriptionId: string, token: string) =>
  api.post<SubscribeResponse>(`/api/v1/customer/subscriptions/${subscriptionId}/renew`, {}, token);

export const cancelSubscription = (subscriptionId: string, reason: string | undefined, token: string) =>
  api.post<PortalSubscriptionOut>(
    `/api/v1/customer/subscriptions/${subscriptionId}/cancel`,
    { reason },
    token,
  );

// --- Admin (requires admin bearer token, except login/mfa) ---

export const adminLogin = (email: string, password: string) =>
  api.post<AdminLoginResponse>("/api/v1/admin/auth/login", { email, password });

export const adminVerifyMfa = (preMfaToken: string, code: string) =>
  api.post<TokenResponse>("/api/v1/admin/auth/mfa/verify", { pre_mfa_token: preMfaToken, code });

export const getAdminMe = (token: string) => api.get<AdminUserOut>("/api/v1/admin/me", token);
