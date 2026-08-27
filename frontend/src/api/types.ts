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

export interface PaymentTransactionOut {
  transaction_id: string;
  gateway: string;
  amount: number;
  currency: string;
  status: string;
  failure_reason?: string | null;
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
