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
}

export interface InvoiceOut {
  invoice_id: string;
  invoice_date: string;
  amount: number;
  tax_amount: number;
  total_amount: number;
  currency: string;
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

export interface CustomerPortalOut {
  customer: Customer;
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
