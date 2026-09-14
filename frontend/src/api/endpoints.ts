/**
 * One function per backend endpoint this frontend uses. Keeping these
 * separate from client.ts's generic request logic means a page component
 * never constructs a URL path or knows an HTTP verb by hand.
 */
import { api, downloadFile, withQuery } from "./client";
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
  ApplicationConfigOut,
  ApplicationGeneralOut,
  ApplicationGeneralUpdateInput,
  ApplicationSubscriptionRulesOut,
  ApplicationSubscriptionRulesUpdateInput,
  EveryticketIntegrationOut,
  EveryticketIntegrationUpdateInput,
  EveryticketWebhookSampleOut,
  NotificationConfigOut,
  NotificationConfigUpdateInput,
  PaymentGatewayConfigOut,
  PaymentGatewayConfigUpdateInput,
  InvoiceEmailResult,
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
  PublicMessagesOut,
  RegistrationFormFieldAdminOut,
  RegistrationFormFieldCreateInput,
  RegistrationFormFieldOut,
  RegistrationFormFieldUpdateInput,
  SecurityConfigOut,
  SecurityConfigUpdateInput,
  SsoLinkOut,
  TaxConfigOut,
  TaxConfigUpdateInput,
  TestDataCleanupOut,
  TestDataGeneratedOut,
  TestEmailResult,
  TestModeStatusOut,
  TestPaymentResult,
  TestWebhookSendResult,
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

/** 2026-09-13 follow-up: the configurable post-subscription confirmation
 * message - read by SubscribePage's mock "done" step and PaymentReturnPage
 * (PayU flow), both only when the just-completed payment's payment_type
 * is "NEW" (a genuinely first-time subscription). */
export const getPublicMessages = () => api.get<PublicMessagesOut>("/api/v1/public/messages");

export const verifyOtp = (otpSessionId: string, code: string) =>
  api.post<OtpVerifyResponse>("/api/v1/public/otp/verify", { otp_session_id: otpSessionId, code });

export const consumeSsoToken = (token: string) =>
  api.post<OtpVerifyResponse>("/api/v1/public/sso/consume", { token });

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

/** Bulk reorder (spec section 51): must list every one of this
 * application's plan codes in the desired order - the backend sets
 * display_order to each code's index and rejects a partial list. */
export const adminReorderPlans = (planCodes: string[], token: string) =>
  api.put<PlanAdminOut[]>("/api/v1/admin/plans/reorder", { plan_codes: planCodes }, token);

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

export const adminGenerateSsoLink = (customerId: string, token: string) =>
  api.post<SsoLinkOut>(`/api/v1/admin/customers/${customerId}/sso-link`, {}, token);

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

export const adminGetInvoiceTaxConfig = (token: string) =>
  api.get<TaxConfigOut>("/api/v1/admin/invoices/tax-config", token);

export const adminUpdateInvoiceTaxConfig = (body: TaxConfigUpdateInput, token: string) =>
  api.put<TaxConfigOut>("/api/v1/admin/invoices/tax-config", body, token);

export const adminDownloadInvoicePdf = (invoiceId: string, token: string) =>
  downloadFile(`/api/v1/admin/invoices/${invoiceId}/pdf`, token, `${invoiceId}.pdf`);

export const adminSendInvoiceEmail = (invoiceId: string, token: string) =>
  api.post<InvoiceEmailResult>(`/api/v1/admin/invoices/${invoiceId}/send-email`, {}, token);

export const customerDownloadInvoicePdf = (invoiceId: string, token: string) =>
  downloadFile(`/api/v1/customer/invoices/${invoiceId}/pdf`, token, `${invoiceId}.pdf`);

// --- Admin: webhook logs ---

export const adminListWebhookEvents = (params: { event_type?: string; limit?: number; offset?: number }, token: string) =>
  api.get<PageOut<WebhookEventOut>>(withQuery("/api/v1/admin/webhooks/events", params), token);

export const adminListWebhookDeliveries = (params: { status?: string; limit?: number; offset?: number }, token: string) =>
  api.get<PageOut<WebhookDeliveryOut>>(withQuery("/api/v1/admin/webhooks/deliveries", params), token);

export const adminRetryWebhookDelivery = (deliveryId: number, token: string) =>
  api.post<WebhookDeliveryOut>(`/api/v1/admin/webhooks/deliveries/${deliveryId}/retry`, {}, token);

// Attempt: unlike Retry (which only resets status back to PENDING for
// the Celery beat schedule to eventually pick up), this makes one real,
// synchronous delivery attempt right now and returns the fully updated
// row - http_status/response_body/response_headers/status/attempt_count
// all reflect what actually happened, immediately.
export const adminAttemptWebhookDelivery = (deliveryId: number, token: string) =>
  api.post<WebhookDeliveryOut>(`/api/v1/admin/webhooks/deliveries/${deliveryId}/attempt`, {}, token);

// Verify connectivity: same request/response shape as the Testing
// module's ad-hoc TEST EVERYTICKET WEBHOOK send (TestWebhookSendResult) -
// this endpoint shares send_ad_hoc_webhook() under the hood, it just
// isn't TEST_MODE-gated and always sends a fixed ping payload.
export const adminVerifyWebhookConnectivity = (token: string) =>
  api.post<TestWebhookSendResult>("/api/v1/admin/webhooks/verify", {}, token);

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


// --- Admin: testing / developer tools (spec section 54) ---

export const testPayment = (
  body: { customer_id: string; plan_code: string; scenario: string },
  token: string,
) => api.post<TestPaymentResult>("/api/v1/admin/testing/payment", body, token);

export const testSubscriptionEvent = (
  body: { subscription_id: string; event: string; target_plan_code?: string },
  token: string,
) => api.post<SubscriptionAdminOut>("/api/v1/admin/testing/subscription-event", body, token);

/** 2026-09-13 follow-up: backs the "Test Everyticket webhook" event
 * dropdown - same five sample wire bodies the admin Configuration
 * screen's "Webhook events" preview shows. */
export const adminGetWebhookSamples = (token: string) =>
  api.get<EveryticketWebhookSampleOut[]>("/api/v1/admin/testing/webhook/samples", token);

export const testWebhookSend = (
  body: { payload: Record<string, unknown>; headers?: Record<string, string> },
  token: string,
) => api.post<TestWebhookSendResult>("/api/v1/admin/testing/webhook/send", body, token);

export const testWebhookFailureSimulate = (statusCode: string, token: string) =>
  api.post<WebhookDeliveryOut>("/api/v1/admin/testing/webhook/simulate-failure", { status_code: statusCode }, token);

export const testEmail = (body: { template_code: string; to: string }, token: string) =>
  api.post<TestEmailResult>("/api/v1/admin/testing/email", body, token);

export const getTestModeStatus = (token: string) => api.get<TestModeStatusOut>("/api/v1/admin/testing/status", token);

export const setOtpMfaBypass = (
  body: { allow_otp_bypass?: boolean; allow_admin_mfa_bypass?: boolean },
  token: string,
) => api.post<TestModeStatusOut>("/api/v1/admin/testing/otp-mfa-bypass", body, token);

export const generateTestData = (token: string) =>
  api.post<TestDataGeneratedOut>("/api/v1/admin/testing/data/generate", {}, token);

export const cleanupTestData = (token: string) =>
  api.post<TestDataCleanupOut>("/api/v1/admin/testing/data/cleanup", {}, token);


// --- Admin: application/security configuration (spec sections 13, 51, 81) ---

export const adminGetApplicationConfig = (token: string) =>
  api.get<ApplicationConfigOut>("/api/v1/admin/config/application", token);

export const adminUpdateGeneralConfig = (body: ApplicationGeneralUpdateInput, token: string) =>
  api.put<ApplicationGeneralOut>("/api/v1/admin/config/application/general", body, token);

export const adminUpdateIntegrationConfig = (body: EveryticketIntegrationUpdateInput, token: string) =>
  api.put<EveryticketIntegrationOut>("/api/v1/admin/config/application/integration", body, token);

export const adminUpdatePaymentGatewayConfig = (body: PaymentGatewayConfigUpdateInput, token: string) =>
  api.put<PaymentGatewayConfigOut>("/api/v1/admin/config/application/payment-gateway", body, token);

export const adminUpdateNotificationConfig = (body: NotificationConfigUpdateInput, token: string) =>
  api.put<NotificationConfigOut>("/api/v1/admin/config/application/notification", body, token);

export const adminUpdateSubscriptionRulesConfig = (body: ApplicationSubscriptionRulesUpdateInput, token: string) =>
  api.put<ApplicationSubscriptionRulesOut>("/api/v1/admin/config/application/subscription-rules", body, token);

export const adminGetSecurityConfig = (token: string) =>
  api.get<SecurityConfigOut>("/api/v1/admin/config/security", token);

export const adminUpdateSecurityConfig = (body: SecurityConfigUpdateInput, token: string) =>
  api.put<SecurityConfigOut>("/api/v1/admin/config/security", body, token);
