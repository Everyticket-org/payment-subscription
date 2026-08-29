/**
 * Admin Testing / Developer Tools (spec section 54) - "mandatory", must
 * allow complete testing without repeatedly performing real
 * payments/emails/webhooks. Every action here hits a TEST_MODE-gated
 * backend endpoint (app/api/v1/admin_testing.py) that reuses the same
 * internal service functions a real request would use - this page is
 * just a thin form-per-tool front end over that API.
 *
 * TEST SSO deliberately has no section here - it reuses the existing
 * "Generate test SSO link" action on AdminCustomerDetailPage (built in
 * increment 9) rather than duplicating it.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  cleanupTestData,
  generateTestData,
  getTestModeStatus,
  setOtpMfaBypass,
  testEmail,
  testPayment,
  testSubscriptionEvent,
  testWebhookFailureSimulate,
  testWebhookSend,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";
import type {
  TestDataCleanupOut,
  TestDataGeneratedOut,
  TestEmailResult,
  TestModeStatusOut,
  TestPaymentResult,
  TestWebhookSendResult,
  SubscriptionAdminOut,
  WebhookDeliveryOut,
} from "../../api/types";

const PAYMENT_SCENARIOS = ["SUCCESS", "FAILED", "PENDING", "TIMEOUT", "DUPLICATE_CALLBACK"];
const SUBSCRIPTION_EVENTS = ["ACTIVATE", "RENEW", "UPGRADE", "DOWNGRADE", "CANCEL", "EXPIRE", "PAYMENT_FAILED"];
const WEBHOOK_FAILURE_CODES = ["400", "401", "404", "500", "timeout"];
const EMAIL_TEMPLATES = ["otp_verification", "payment_success", "payment_failed", "subscription_cancelled", "renewal_reminder"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="admin-panel">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

export function AdminTestingPage() {
  const { adminToken } = useAuth();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // TEST MODE status
  const [status, setStatus] = useState<TestModeStatusOut | null>(null);

  // TEST PAYMENT
  const [payCustomerId, setPayCustomerId] = useState("");
  const [payPlanCode, setPayPlanCode] = useState("BASIC");
  const [payScenario, setPayScenario] = useState("SUCCESS");
  const [payResult, setPayResult] = useState<TestPaymentResult | null>(null);

  // TEST SUBSCRIPTION EVENTS
  const [eventSubId, setEventSubId] = useState("");
  const [event, setEvent] = useState("RENEW");
  const [eventTargetPlan, setEventTargetPlan] = useState("");
  const [eventResult, setEventResult] = useState<SubscriptionAdminOut | null>(null);

  // TEST EVERYTICKET WEBHOOK
  const [webhookJson, setWebhookJson] = useState('{\n  "event_type": "test.manual",\n  "message": "hello from admin testing"\n}');
  const [webhookResult, setWebhookResult] = useState<TestWebhookSendResult | null>(null);

  // WEBHOOK FAILURE SIMULATOR
  const [failureCode, setFailureCode] = useState("500");
  const [failureResult, setFailureResult] = useState<WebhookDeliveryOut | null>(null);

  // TEST EMAIL
  const [emailTemplate, setEmailTemplate] = useState("payment_success");
  const [emailTo, setEmailTo] = useState("");
  const [emailResult, setEmailResult] = useState<TestEmailResult | null>(null);

  // TEST DATA GENERATOR
  const [generated, setGenerated] = useState<TestDataGeneratedOut | null>(null);
  const [cleanup, setCleanup] = useState<TestDataCleanupOut | null>(null);

  useEffect(() => {
    if (!adminToken) return;
    getTestModeStatus(adminToken).then(setStatus).catch(setError);
  }, [adminToken]);

  async function run<T>(fn: () => Promise<T>, onResult: (r: T) => void) {
    if (!adminToken) return;
    setBusy(true);
    setError(null);
    try {
      onResult(await fn());
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h1>Testing / Developer Tools</h1>
      <p className="hint">
        Every action below only works while TEST_MODE is enabled on the backend, and is force-disabled in production
        regardless of any configuration mistake.
      </p>
      <ErrorBanner error={error} />

      {status && (
        <div className="admin-panel">
          <h2>Environment status</h2>
          <dl className="summary-list">
            <dt>Environment</dt>
            <dd>{status.environment}</dd>
            <dt>TEST_MODE</dt>
            <dd>{status.test_mode ? "ON" : "off"}</dd>
            <dt>Skip Customer OTP</dt>
            <dd>{status.allow_otp_bypass ? "ON" : "off"}</dd>
            <dt>Skip Admin MFA</dt>
            <dd>{status.allow_admin_mfa_bypass ? "ON" : "off"}</dd>
          </dl>
          <div className="button-row">
            <button
              className="button button-secondary"
              disabled={busy}
              onClick={() =>
                run(
                  () => setOtpMfaBypass({ allow_otp_bypass: !status.allow_otp_bypass }, adminToken!),
                  setStatus,
                )
              }
            >
              {status.allow_otp_bypass ? "Disable OTP bypass" : "Enable OTP bypass"}
            </button>
            <button
              className="button button-secondary"
              disabled={busy}
              onClick={() =>
                run(
                  () => setOtpMfaBypass({ allow_admin_mfa_bypass: !status.allow_admin_mfa_bypass }, adminToken!),
                  setStatus,
                )
              }
            >
              {status.allow_admin_mfa_bypass ? "Disable MFA bypass" : "Enable MFA bypass"}
            </button>
          </div>
          <p className="hint">
            These toggles change the running server's in-memory settings only - they reset to whatever `.env` says on
            the next restart, and never take effect outside development/staging.
          </p>
        </div>
      )}

      <Section title="Test payment">
        <div className="inline-form">
          <label>
            Customer ID
            <input value={payCustomerId} onChange={(e) => setPayCustomerId(e.target.value)} placeholder="CUS-..." />
          </label>
          <label>
            Plan code
            <input value={payPlanCode} onChange={(e) => setPayPlanCode(e.target.value.toUpperCase())} placeholder="BASIC" />
          </label>
          <label>
            Scenario
            <select value={payScenario} onChange={(e) => setPayScenario(e.target.value)}>
              {PAYMENT_SCENARIOS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button button-primary"
            disabled={busy || !payCustomerId || !payPlanCode}
            onClick={() =>
              run(
                () => testPayment({ customer_id: payCustomerId, plan_code: payPlanCode, scenario: payScenario }, adminToken!),
                setPayResult,
              )
            }
          >
            Simulate payment
          </button>
        </div>
        {payResult && (
          <p className="hint">
            {payResult.note} Payment status: <strong>{payResult.payment.status}</strong>, subscription status:{" "}
            <strong>{payResult.subscription.status}</strong>
            {payResult.invoice_id ? `, invoice: ${payResult.invoice_id}` : ""}.
          </p>
        )}
      </Section>

      <Section title="Test subscription events">
        <div className="inline-form">
          <label>
            Subscription ID
            <input value={eventSubId} onChange={(e) => setEventSubId(e.target.value)} placeholder="SUB-..." />
          </label>
          <label>
            Event
            <select value={event} onChange={(e) => setEvent(e.target.value)}>
              {SUBSCRIPTION_EVENTS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          {(event === "UPGRADE" || event === "DOWNGRADE") && (
            <label>
              Target plan code
              <input value={eventTargetPlan} onChange={(e) => setEventTargetPlan(e.target.value.toUpperCase())} placeholder="PROFESSIONAL" />
            </label>
          )}
          <button
            className="button button-primary"
            disabled={busy || !eventSubId}
            onClick={() =>
              run(
                () =>
                  testSubscriptionEvent(
                    { subscription_id: eventSubId, event, target_plan_code: eventTargetPlan || undefined },
                    adminToken!,
                  ),
                setEventResult,
              )
            }
          >
            Send test event
          </button>
        </div>
        {eventResult && (
          <p className="hint">
            Subscription {eventResult.subscription_id} is now <strong>{eventResult.status}</strong> on plan{" "}
            {eventResult.plan_code}.
          </p>
        )}
      </Section>

      <Section title="Test Everyticket webhook">
        <div className="inline-form">
          <label style={{ width: "100%" }}>
            JSON body
            <textarea rows={6} value={webhookJson} onChange={(e) => setWebhookJson(e.target.value)} />
          </label>
          <button
            className="button button-primary"
            disabled={busy}
            onClick={() =>
              run(() => {
                let parsed: Record<string, unknown>;
                try {
                  parsed = JSON.parse(webhookJson);
                } catch {
                  throw new Error("Body is not valid JSON");
                }
                return testWebhookSend({ payload: parsed }, adminToken!);
              }, setWebhookResult)
            }
          >
            Send test webhook
          </button>
        </div>
        {webhookResult && (
          <div className="hint">
            <p>
              {webhookResult.sent ? "Sent" : "Failed to send"}
              {webhookResult.http_status !== null && webhookResult.http_status !== undefined
                ? ` - HTTP ${webhookResult.http_status}`
                : ""}
              {webhookResult.elapsed_ms !== undefined ? ` (${webhookResult.elapsed_ms} ms)` : ""}
            </p>
            {webhookResult.error && <p>Error: {webhookResult.error}</p>}
            {webhookResult.response_body && (
              <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{webhookResult.response_body}</pre>
            )}
          </div>
        )}
      </Section>

      <Section title="Webhook failure simulator">
        <div className="inline-form">
          <label>
            Simulated response
            <select value={failureCode} onChange={(e) => setFailureCode(e.target.value)}>
              {WEBHOOK_FAILURE_CODES.map((c) => (
                <option key={c} value={c}>
                  {c === "timeout" ? "timeout" : `HTTP ${c}`}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button button-primary"
            disabled={busy}
            onClick={() => run(() => testWebhookFailureSimulate(failureCode, adminToken!), setFailureResult)}
          >
            Simulate failure
          </button>
        </div>
        {failureResult && (
          <p className="hint">
            Delivery status <strong>{failureResult.status}</strong>, attempt #{failureResult.attempt_count}
            {failureResult.next_retry_at ? `, next retry at ${new Date(failureResult.next_retry_at).toLocaleString()}` : ""}.
          </p>
        )}
      </Section>

      <Section title="Test email">
        <div className="inline-form">
          <label>
            Template
            <select value={emailTemplate} onChange={(e) => setEmailTemplate(e.target.value)}>
              {EMAIL_TEMPLATES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Send to
            <input type="email" value={emailTo} onChange={(e) => setEmailTo(e.target.value)} placeholder="you@example.com" />
          </label>
          <button
            className="button button-primary"
            disabled={busy || !emailTo}
            onClick={() => run(() => testEmail({ template_code: emailTemplate, to: emailTo }, adminToken!), setEmailResult)}
          >
            Send test email
          </button>
        </div>
        {emailResult && (
          <p className="hint">
            {emailResult.sent ? "Sent" : "Not sent"} - status: <strong>{emailResult.status ?? "unknown"}</strong>
            {emailResult.provider_response ? ` (${emailResult.provider_response})` : ""}.
          </p>
        )}
      </Section>

      <Section title="Test SSO">
        <p className="hint">
          Open a customer's detail page (Customers → pick a customer) and use the "Generate test SSO link" action
          there - it reuses this same TEST_MODE gate and lets you open the customer portal through a real signed SSO
          link.
        </p>
      </Section>

      <Section title="Test data generator">
        <div className="button-row">
          <button className="button button-primary" disabled={busy} onClick={() => run(() => generateTestData(adminToken!), setGenerated)}>
            Generate test data set
          </button>
          <button className="button button-danger" disabled={busy} onClick={() => run(() => cleanupTestData(adminToken!), setCleanup)}>
            Clean up all TEST- data
          </button>
        </div>
        {generated && (
          <p className="hint">
            Generated customer {generated.customer_id}, plan {generated.plan_code}, subscription {generated.subscription_id}
            {generated.invoice_id ? `, invoice ${generated.invoice_id}` : ""}, Everyticket mapping {generated.external_customer_id}.
          </p>
        )}
        {cleanup && (
          <p className="hint">
            Cleaned up {cleanup.plans_deleted} test plan(s), {cleanup.customers_deleted} test customer(s), and{" "}
            {cleanup.subscriptions_deleted} test subscription(s).
          </p>
        )}
      </Section>
    </section>
  );
}
