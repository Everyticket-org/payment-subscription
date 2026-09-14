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
 *
 * 2026-09-13 follow-up ("Remove Test Payment section, Remove Test
 * Subscription Events section"): both UI sections are gone from this
 * page. Their backend endpoints (/testing/payment, /testing/subscription-
 * event) are deliberately left untouched - same "dead UI, live backend"
 * precedent this codebase already uses elsewhere - so direct API use and
 * their existing tests are unaffected.
 *
 * "Test Everyticket webhook" gained an Event dropdown ("Give dropdown of
 * Events like activate etc.. Based on selection JSON editor automatically
 * should be filled with required structure") - selecting one fills the
 * JSON editor with the exact wire body (GET /testing/webhook/samples,
 * the same five samples the admin Configuration screen previews) a real
 * delivery of that event would send, ready to edit or send as-is.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  adminGetWebhookSamples,
  cleanupTestData,
  generateTestData,
  getTestModeStatus,
  setOtpMfaBypass,
  testEmail,
  testWebhookFailureSimulate,
  testWebhookSend,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type {
  EveryticketWebhookSampleOut,
  TestDataCleanupOut,
  TestDataGeneratedOut,
  TestEmailResult,
  TestModeStatusOut,
  TestWebhookSendResult,
  WebhookDeliveryOut,
} from "../../api/types";

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
  const toast = useToast();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // TEST MODE status
  const [status, setStatus] = useState<TestModeStatusOut | null>(null);

  // TEST EVERYTICKET WEBHOOK
  const [webhookSamples, setWebhookSamples] = useState<EveryticketWebhookSampleOut[]>([]);
  const [webhookEvent, setWebhookEvent] = useState("");
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
    adminGetWebhookSamples(adminToken).then(setWebhookSamples).catch(setError);
  }, [adminToken]);

  async function run<T>(fn: () => Promise<T>, onResult: (r: T) => void, successMessage?: string) {
    if (!adminToken) return;
    setBusy(true);
    setError(null);
    try {
      onResult(await fn());
      toast.success(successMessage ?? "Done");
    } catch (err) {
      setError(err);
      toast.error(err);
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
                  status.allow_otp_bypass ? "OTP bypass disabled" : "OTP bypass enabled",
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
                  status.allow_admin_mfa_bypass ? "MFA bypass disabled" : "MFA bypass enabled",
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

      <Section title="Test Everyticket webhook">
        <div className="inline-form">
          <label>
            Event
            <select
              value={webhookEvent}
              onChange={(e) => {
                const eventType = e.target.value;
                setWebhookEvent(eventType);
                const sample = webhookSamples.find((s) => s.event === eventType);
                if (sample) setWebhookJson(JSON.stringify(sample.payload, null, 2));
              }}
            >
              <option value="">Custom / manual JSON...</option>
              {webhookSamples.map((s) => (
                <option key={s.event} value={s.event} title={s.trigger}>
                  {s.event}
                </option>
              ))}
            </select>
          </label>
        </div>
        {webhookEvent && (
          <p className="hint">{webhookSamples.find((s) => s.event === webhookEvent)?.trigger}</p>
        )}
        <div className="inline-form">
          <label style={{ width: "100%" }}>
            JSON body
            <textarea rows={10} value={webhookJson} onChange={(e) => setWebhookJson(e.target.value)} />
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
              }, setWebhookResult, "Test webhook sent")
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
            onClick={() => run(() => testWebhookFailureSimulate(failureCode, adminToken!), setFailureResult, "Failure simulated")}
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
            onClick={() => run(() => testEmail({ template_code: emailTemplate, to: emailTo }, adminToken!), setEmailResult, "Test email sent")}
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
        <p className="hint">
          In production, Everyticket's own backend generates this link itself by calling{" "}
          <code>POST /api/v1/integration/sso/generate-link</code> - see the "SSO API access" fields on Configuration
          → Everyticket Integration for the API key/secret it authenticates with.
        </p>
      </Section>

      <Section title="Test data generator">
        <div className="button-row">
          <button className="button button-primary" disabled={busy} onClick={() => run(() => generateTestData(adminToken!), setGenerated, "Test data generated")}>
            Generate test data set
          </button>
          <button className="button button-danger" disabled={busy} onClick={() => run(() => cleanupTestData(adminToken!), setCleanup, "Test data cleaned up")}>
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
