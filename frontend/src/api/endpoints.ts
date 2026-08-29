/**
 * One function per backend endpoint this frontend uses. Keeping these
 * separate from client.ts's generic request logic means a page component
 * never constructs a URL path or knows an HTTP verb by hand.
 */
import { api, withQuery } from "./client";
import type {
  AdminLoginResponse,
  AdminUserOut,
  AuditLogOut,
  CustomerAdminDetailOut,
  CustomerAdminListItem,
  CustomerPortalOut,
  DashboardStatsOut,
  IdentifyResponse,
  InvoiceAdminOut,
  MockCallbackResult,
  NotificationLogOut,
  NotificationTemplateOut,
  OtpVerifyResponse,
  PageOut,
  PaymentAdminOut,
  Plan,
  PlanAdminOut,
  PlanCreateInput,
  PlanFeatureAdminOut,
  PlanTransitionOut,
  PlanUpdateInput,
  PortalSubscriptionOut,
  RegistrationFormFieldAdminOut,
  RegistrationFormFieldCreateInput,
  RegistrationFormFieldOut,
  RegistrationFormFieldUpdateInput,
  SubscribeResponse,
  SubscriptionAdminOut,
  SubscriptionDetailAdminOut,
  TokenResponse,
  WebhookDeliveryOut,
  WebhookEventOut,
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

export const getRegistrationForm = () =>
  api.get<RegistrationFormFieldOut[]>("/api/v1/public/registration-form");

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

// --- Admin: dashboard ---

export const getAdminDashboard = (token: string) => api.get<DashboardStatsOut>("/api/v1/admin/dashboard", token);

// --- Admin: plans / features / transitions ---

export const adminListPlans = (token: string) => api.get<PlanAdminOut[]>("/api/v1/admin/plans", token);

export const adminGetPlan = (planCode: string, token: string) =>
  api.get<PlanAdminOut>(`/api/v1/admin/plans/${planCode}`, token);

export const adminCreatePlan = (body: PlanCreateInput, token: string) =>
  api.post<PlanAdminOut>("/api/v1/admin/plans", body, token);

export const adminUpdatePlan = (planCode: string, body: PlanUpdateInput, token: string) =>
  api.put<PlanAdminOut>(`/api/v1/admin/plans/${planCode}`, body, token);

export const adminAddPlanFeature = (
  planCode: string,
  body: { feature_key: string; feature_label: string; feature_value?: string; display_order?: number },
  token: string,
) => api.post<PlanFeatureAdminOut>(`/api/v1/admin/plans/${planCode}/features`, body, token);

export const adminUpdatePlanFeature = (
  planCode: string,
  featureId: number,
  body: { feature_label?: string; feature_value?: string; display_order?: number },
  token: string,
) => api.put<PlanFeatureAdminOut>(`/api/v1/admin/plans/${planCode}/features/${featureId}`, body, token);

export const adminDeletePlanFeature = (planCode: string, featureId: number, token: string) =>
  api.delete<void>(`/api/v1/admin/plans/${planCode}/features/${featureId}`, token);

export const adminListPlanTransitions = (token: string) =>
  api.get<PlanTransitionOut[]>("/api/v1/admin/plans/transitions", token);

export const adminCreatePlanTransition = (
  body: { from_plan_code: string; to_plan_code: string; transition_type: "UPGRADE" | "DOWNGRADE" },
  token: string,
) => api.post<PlanTransitionOut>("/api/v1/admin/plans/transitions", body, token);

export const adminDeletePlanTransition = (transitionId: number, token: string) =>
  api.delete<void>(`/api/v1/admin/plans/transitions/${transitionId}`, token);

// --- Admin: customers ---

export const adminListCustomers = (
  params: { q?: string; status?: string; limit?: number; offset?: number },
  token: string,
) => api.get<PageOut<CustomerAdminListItem>>(withQuery("/api/v1/admin/customers", params), token);

export const adminGetCustomer = (customerId: string, token: string) =>
  api.get<CustomerAdminDetailOut>(`/api/v1/admin/customers/${customerId}`, token);

export const adminSuspendCustomer = (customerId: string, reason: string | undefined, token: string) =>
  api.post<{ customer_id: string; status: string }>(
    `/api/v1/admin/customers/${customerId}/suspend`,
    { reason },
    token,
  );

export const adminActivateCustomer = (customerId: string, token: string) =>
  api.post<{ customer_id: string; status: string }>(`/api/v1/admin/customers/${customerId}/activate`, {}, token);

// --- Admin: subscriptions ---

export const adminListSubscriptions = (
  params: { status?: string; plan_code?: string; customer_id?: string; limit?: number; offset?: number },
  token: string,
) =>
  api.get<PageOut<SubscriptionAdminOut>>(withQuery("/api/v1/admin/subscriptions", params), token);

export const adminGetSubscription = (subscriptionId: string, token: string) =>
  api.get<SubscriptionDetailAdminOut>(`/api/v1/admin/subscriptions/${subscriptionId}`, token);

// --- Admin: payments ---

export const adminListPayments = (
  params: { status?: string; gateway?: string; customer_id?: string; limit?: number; offset?: number },
  token: string,
) => api.get<PageOut<PaymentAdminOut>>(withQuery("/api/v1/admin/payments", params), token);

export const adminGetPayment = (transactionId: string, token: string) =>
  api.get<PaymentAdminOut>(`/api/v1/admin/payments/${transactionId}`, token);

// --- Admin: invoices ---

export const adminListInvoices = (params: { customer_id?: string; limit?: number; offset?: number }, token: string) =>
  api.get<PageOut<InvoiceAdminOut>>(withQuery("/api/v1/admin/invoices", params), token);

export const adminGetInvoice = (invoiceId: string, token: string) =>
  api.get<InvoiceAdminOut>(`/api/v1/admin/invoices/${invoiceId}`, token);

// --- Admin: webhook logs ---

export const adminListWebhookEvents = (params: { event_type?: string; limit?: number; offset?: number }, token: string) =>
  api.get<PageOut<WebhookEventOut>>(withQuery("/api/v1/admin/webhooks/events", params), token);

export const adminListWebhookDeliveries = (params: { status?: string; limit?: number; offset?: number }, token: string) =>
  api.get<PageOut<WebhookDeliveryOut>>(withQuery("/api/v1/admin/webhooks/deliveries", params), token);

export const adminRetryWebhookDelivery = (deliveryId: number, token: string) =>
  api.post<WebhookDeliveryOut>(`/api/v1/admin/webhooks/deliveries/${deliveryId}/retry`, {}, token);

// --- Admin: notification templates / logs ---

export const adminListNotificationTemplates = (token: string) =>
  api.get<NotificationTemplateOut[]>("/api/v1/admin/notifications/templates", token);

export const adminUpdateNotificationTemplate = (
  templateCode: string,
  body: { subject?: string; body_html?: string; body_text?: string; active?: boolean },
  token: string,
) => api.put<NotificationTemplateOut>(`/api/v1/admin/notifications/templates/${templateCode}`, body, token);

export const adminListNotificationLogs = (
  params: { status?: string; template_code?: string; recipient?: string; limit?: number; offset?: number },
  token: string,
) => api.get<PageOut<NotificationLogOut>>(withQuery("/api/v1/admin/notifications/logs", params), token);

// --- Admin: registration form fields ---

export const adminListRegistrationFormFields = (token: string) =>
  api.get<RegistrationFormFieldAdminOut[]>("/api/v1/admin/registration-form", token);

export const adminCreateRegistrationFormField = (body: RegistrationFormFieldCreateInput, token: string) =>
  api.post<RegistrationFormFieldAdminOut>("/api/v1/admin/registration-form", body, token);

export const adminUpdateRegistrationFormField = (
  fieldId: number,
  body: RegistrationFormFieldUpdateInput,
  token: string,
) => api.put<RegistrationFormFieldAdminOut>(`/api/v1/admin/registration-form/${fieldId}`, body, token);

// --- Admin: audit logs ---

export const adminListAuditLogs = (
  params: { entity_type?: string; entity_id?: string; actor?: string; action?: string; limit?: number; offset?: number },
  token: string,
) => api.get<PageOut<AuditLogOut>>(withQuery("/api/v1/admin/audit-logs", params), token);
