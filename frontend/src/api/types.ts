/**
 * Types mirroring the backend's Pydantic schemas (see each backend
 * module's schemas.py, e.g. backend/app/plans/schemas.py). Kept
 * hand-written and close to the wire shape rather than generated, since
 * the backend has no OpenAPI-codegen step wired up yet - if the two
 * drift, the dev-mode network tab is the source of truth until that's
 * added.
 */

export interface Plan {
  plan_code: string;
  name: string;
  price: number;
  currency: string;
  billing_interval: string;
  billing_frequency: number;
  description?: string | null;
  is_trial?: boolean;
  trial_period_days?: number | null;
}

export interface Customer {
  customer_id: string;
  email: string | null;
  mobile: string | null;
  email_verified: boolean;
  mobile_verified: boolean;
  status: string;
}

export interface SubscriptionOut {
  subscription_id: string;
  status: string;
  provisioning_status: string;
  starts_at: string | null;
  expires_at: string | null;
}

export interface PortalSubscriptionOut extends SubscriptionOut {
  plan_code: string;
  plan_name: string;
  price: number;
  currency: string;
  billing_interval: string;
  billing_frequency: number;
  is_trial?: boolean;
}

export interface PayUCheckoutFields {
  key: string;
  txnid: string;
  amount: string;
  productinfo: string;
  firstname: string;
  email: string;
  phone: string;
  surl: string;
  furl: string;
  hash: string;
}

export interface PaymentCheckout {
  action_url: string;
  method: string;
  fields: PayUCheckoutFields;
}

export interface PaymentTransactionOut {
  transaction_id: string;
  gateway: string;
  amount: number;
  currency: string;
  status: string;
  failure_reason?: string | null;
  /** Present only for a PENDING PayU payment - the hosted-checkout form
   * the browser must POST to PayU's own page. Absent for the mock
   * gateway, which stays a same-page "simulate" button. */
  checkout?: PaymentCheckout | null;
  /** Only populated on GET /customer/me's payments list (portal combined
   * table) - see backend PaymentTransactionOut.subscription_ref/created_at. */
  created_at?: string | null;
  subscription_ref?: string | null;
}

export interface InvoiceOut {
  invoice_id: string;
  invoice_date: string;
  amount: number;
  tax_amount: number;
  total_amount: number;
  currency: string;
  /** Only populated on GET /customer/me's invoices list (portal combined
   * table) - see backend InvoiceOut.subscription_ref/transaction_id. */
  subscription_ref?: string | null;
  transaction_id?: string | null;
}

export interface SubscribeResponse {
  customer: Customer;
  subscription: SubscriptionOut;
  payment: PaymentTransactionOut;
}

export interface IdentifyResponse {
  match_status: "none" | "exact" | "conflict";
  otp_session_id: string | null;
  debug_otp_code: string | null;
  message: string;
}

export interface OtpVerifyResponse {
  customer: Customer;
  access_token: string;
  token_type: string;
}

export interface TestPaymentResult {
  payment: PaymentAdminOut;
  subscription: SubscriptionAdminOut;
  invoice_id: string | null;
  note: string;
}

export interface TestWebhookSendResult {
  sent: boolean;
  request?: { url: string; headers: Record<string, string>; body: unknown };
  http_status: number | null;
  response_body?: string;
  error?: string;
  elapsed_ms?: number;
}

export interface TestEmailResult {
  sent: boolean;
  status: string | null;
  provider_response: string | null;
}

export interface TestModeStatusOut {
  environment: string;
  test_mode: boolean;
  allow_otp_bypass: boolean;
  allow_admin_mfa_bypass: boolean;
}

export interface TestDataGeneratedOut {
  customer_id: string;
  plan_code: string;
  subscription_id: string;
  transaction_id: string;
  invoice_id: string | null;
  external_customer_id: string;
}

export interface TestDataCleanupOut {
  plans_deleted: number;
  customers_deleted: number;
  subscriptions_deleted: number;
}

export interface SsoLinkOut {
  sso_token: string;
  consume_url: string;
  expires_at: string;
}

export interface CustomerPortalOut {
  customer: Customer;
  registration_data: RegistrationDataOut[];
  active_subscription: PortalSubscriptionOut | null;
  subscriptions: PortalSubscriptionOut[];
  payments: PaymentTransactionOut[];
  invoices: InvoiceOut[];
}

export interface MockCallbackResult {
  payment: PaymentTransactionOut;
  subscription: SubscriptionOut;
  invoice_id: string | null;
}

export interface AdminLoginResponse {
  mfa_required: boolean;
  pre_mfa_token: string | null;
  access_token: string | null;
  refresh_token: string | null;
  token_type: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AdminUserOut {
  email: string;
  full_name: string;
  is_active: boolean;
  mfa_enabled: boolean;
  roles: string[];
}

/** Shape of the {"error_code": ..., "message": ...} body every AppError
 * subclass produces (see backend/app/main.py's exception handler). */
export interface ApiErrorBody {
  error_code: string;
  message: string;
}


// --- Admin (mirrors backend/app/api/v1/admin_*.py + the schemas they use) ---

export interface PageOut<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface DashboardStatsOut {
  active_subscriptions: number;
  new_subscriptions_30d: number;
  revenue_30d: number;
  revenue_currency: string;
  failed_payments_30d: number;
  expiring_within_7d: number;
  expired_total: number;
  provisioning_failures: number;
  webhook_failures: number;
}

export interface PlanFeatureAdminOut {
  id: number;
  feature_key: string;
  feature_label: string;
  feature_value?: string | null;
  display_order: number;
}

export interface PlanAdminOut {
  plan_code: string;
  name: string;
  description?: string | null;
  price: number;
  currency: string;
  billing_interval: string;
  billing_frequency: number;
  active: boolean;
  display_order: number;
  is_trial: boolean;
  trial_period_days?: number | null;
  features: PlanFeatureAdminOut[];
}

export interface PlanCreateInput {
  plan_code: string;
  name: string;
  description?: string;
  price: number;
  currency?: string;
  billing_interval?: "month" | "year";
  billing_frequency?: number;
  display_order?: number;
  is_trial?: boolean;
  trial_period_days?: number | null;
}

export interface PlanUpdateInput {
  name?: string;
  description?: string;
  price?: number;
  currency?: string;
  billing_interval?: "month" | "year";
  billing_frequency?: number;
  active?: boolean;
  display_order?: number;
  is_trial?: boolean;
  trial_period_days?: number | null;
}

export interface PlanTransitionOut {
  id: number;
  from_plan_code: string;
  to_plan_code: string;
  transition_type: "UPGRADE" | "DOWNGRADE";
}

export interface CustomerAdminListItem {
  customer_id: string;
  email: string;
  mobile: string;
  status: string;
  created_at: string;
}

export interface RegistrationDataOut {
  application_id: number;
  subscription_id: number | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface ApplicationMappingOut {
  external_customer_id: string | null;
  external_instance_id: string | null;
}

export interface SubscriptionAdminOut {
  subscription_id: string;
  customer_id: string;
  plan_code: string;
  plan_name: string;
  status: string;
  provisioning_status: string;
  starts_at: string | null;
  expires_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  created_at: string;
  is_trial?: boolean;
}

export interface SubscriptionHistoryOut {
  event_type: string;
  occurred_at: string;
  event_metadata: Record<string, unknown> | null;
}

export interface SubscriptionDetailAdminOut {
  subscription: SubscriptionAdminOut;
  history: SubscriptionHistoryOut[];
}

export interface PaymentAdminOut {
  transaction_id: string;
  customer_id: string;
  subscription_id: string;
  plan_code: string;
  gateway: string;
  gateway_transaction_id?: string | null;
  amount: number;
  currency: string;
  payment_type: string;
  status: string;
  failure_reason?: string | null;
  created_at: string;
  updated_at: string;
  raw_gateway_response?: Record<string, unknown> | null;
}

export interface InvoiceItemOut {
  description: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface InvoiceAdminOut {
  invoice_id: string;
  customer_id: string;
  subscription_id: string;
  transaction_id: string;
  invoice_date: string;
  billing_period_start: string;
  billing_period_end: string;
  gst_number?: string | null;
  amount: number;
  tax_amount: number;
  total_amount: number;
  currency: string;
  items: InvoiceItemOut[];
}

// Restructured 2026-09 into 4 admin Configuration sections - see
// backend app/applications/config_schemas.py's module docstring for the
// full rationale (why application_url/logo/favicon/support/timezone/active,
// api_url and sso_secret are no longer on these screens even though their
// backend columns/behavior are unchanged).

export interface ApplicationGeneralOut {
  code: string;
  name: string;
  currency: string;
  gateway_mode: string; // test | live - "Live/Test Mode"
}

export interface ApplicationGeneralUpdateInput {
  name: string;
  currency: string;
  gateway_mode: string;
}

export interface PayUCredentialsOut {
  merchant_key_is_set: boolean;
  merchant_salt_is_set: boolean;
}

export interface PayUCredentialsInput {
  merchant_key?: string | null;
  merchant_salt?: string | null;
}

export interface PaymentGatewayConfigOut {
  default_gateway: string;
  available_gateways: string[];
  payu_test: PayUCredentialsOut;
  payu_live: PayUCredentialsOut;
  return_url: string | null;
  payu_webhook_base_url: string | null;
}

export interface PaymentGatewayConfigUpdateInput {
  default_gateway: string;
  payu_test?: PayUCredentialsInput | null;
  payu_live?: PayUCredentialsInput | null;
  return_url?: string | null;
  payu_webhook_base_url?: string | null;
}

export interface EveryticketWebhookSampleOut {
  event: string;
  trigger: string;
  payload: Record<string, unknown>;
}

export interface EveryticketIntegrationOut {
  secret_key_is_set: boolean;
  webhook_url: string | null;
  extra_params: Record<string, string>;
  retry_limit: number | null;
  default_retry_limit: number;
  escalation_emails: string | null;
  escalation_email_subject: string | null;
  escalation_email_body: string | null;
  archive_after_days: number | null;
  webhook_samples: EveryticketWebhookSampleOut[];
}

export interface EveryticketIntegrationUpdateInput {
  secret_key?: string | null;
  webhook_url?: string | null;
  extra_params?: Record<string, string> | null;
  retry_limit?: number | null;
  escalation_emails?: string | null;
  escalation_email_subject?: string | null;
  escalation_email_body?: string | null;
  archive_after_days?: number | null;
}

export interface NotificationConfigOut {
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_username: string | null;
  smtp_password_is_set: boolean;
  smtp_use_tls: boolean | null;
  email_sender_name: string | null;
  email_sender_address: string | null;
  email_reply_to: string | null;
}

export interface NotificationConfigUpdateInput {
  smtp_host?: string | null;
  smtp_port?: number | null;
  smtp_username?: string | null;
  smtp_password?: string | null;
  smtp_use_tls?: boolean | null;
  email_provider?: string;
  email_sender_name?: string | null;
  email_sender_address?: string | null;
  email_reply_to?: string | null;
}

export interface ApplicationSubscriptionRulesOut {
  allow_upgrade: boolean;
  allow_downgrade: boolean;
  allow_cancellation: boolean;
  cancellation_behavior: string;
  renewal_enabled: boolean;
  repurchase_enabled: boolean;
}

export type ApplicationSubscriptionRulesUpdateInput = ApplicationSubscriptionRulesOut;

export interface ApplicationConfigOut {
  general: ApplicationGeneralOut;
  payment_gateway: PaymentGatewayConfigOut;
  integration: EveryticketIntegrationOut;
  notification: NotificationConfigOut;
  subscription_rules: ApplicationSubscriptionRulesOut;
}

export interface SecurityConfigOut {
  otp_length: number;
  otp_expiry_seconds: number;
  otp_max_attempts: number;
  otp_resend_cooldown_seconds: number;
  allow_otp_bypass: boolean;
  allow_admin_mfa_bypass: boolean;
  test_mode: boolean;
}

export interface SecurityConfigUpdateInput {
  otp_length: number;
  otp_expiry_seconds: number;
  otp_max_attempts: number;
  otp_resend_cooldown_seconds: number;
}

export interface TaxConfigOut {
  gst_rate_percent: number;
  seller_gstin: string | null;
  tax_label: string;
}

export interface TaxConfigUpdateInput {
  gst_rate_percent: number;
  seller_gstin?: string | null;
  tax_label?: string;
}

export interface InvoiceEmailResult {
  sent: boolean;
  to: string | null;
}

export interface CustomerAdminDetailOut {
  customer: Customer;
  registration_data: RegistrationDataOut[];
  application_mapping: ApplicationMappingOut | null;
  subscriptions: SubscriptionAdminOut[];
  payments: PaymentAdminOut[];
  invoices: InvoiceAdminOut[];
}

export interface WebhookDeliveryOut {
  id: number;
  destination_url: string;
  status: string;
  attempt_count: number;
  http_status?: number | null;
  response_body?: string | null;
  last_attempt_at?: string | null;
  next_retry_at?: string | null;
}

export interface WebhookEventOut {
  event_id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  created_at: string;
  deliveries: WebhookDeliveryOut[];
}

export interface NotificationTemplateOut {
  template_code: string;
  channel: string;
  subject: string;
  body_html: string;
  body_text?: string | null;
  active: boolean;
}

export interface NotificationLogOut {
  template_code: string;
  channel: string;
  recipient: string;
  status: string;
  provider_response?: string | null;
  related_entity_type?: string | null;
  related_entity_id?: string | null;
  created_at: string;
}

export interface AuditLogOut {
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  old_value?: Record<string, unknown> | null;
  new_value?: Record<string, unknown> | null;
  ip_address?: string | null;
  created_at: string;
}


// --- Registration form fields (spec sections 8, 18, 51) ---

export interface RegistrationFormFieldOut {
  field_key: string;
  label: string;
  field_type: string;
  required: boolean;
  validation_rules?: Record<string, unknown> | null;
  placeholder?: string | null;
  help_text?: string | null;
  options?: string[] | null;
  display_order: number;
}

export interface RegistrationFormFieldAdminOut extends RegistrationFormFieldOut {
  id: number;
  active: boolean;
}

export interface RegistrationFormFieldCreateInput {
  field_key: string;
  label: string;
  field_type: string;
  required?: boolean;
  placeholder?: string;
  help_text?: string;
  options?: string[];
  display_order?: number;
}

export interface RegistrationFormFieldUpdateInput {
  label?: string;
  required?: boolean;
  placeholder?: string;
  help_text?: string;
  options?: string[];
  display_order?: number;
  active?: boolean;
}
