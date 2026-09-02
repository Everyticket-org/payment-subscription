/**
 * Admin Configuration, restructured 2026-09 (Vishal's explicit 4-section
 * layout) into: Application (name/currency/Live-Test-Mode only),
 * Payment Gateway (gateway dropdown + per-mode PayU credentials shown
 * only when PayU is selected, plus the Return URL/PayU webhook URL the
 * payment flow redirects through), Everyticket Integration (secret key,
 * webhook URL, retry limit, an archive-after-days threshold, a
 * read-only sample-JSON preview of the five real webhook event types,
 * and an escalation email sent once a delivery is exhausted), and
 * Notifications (SMTP transport + sender overrides). "Subscription
 * rules" and "Security" configuration keep their existing backend
 * endpoints and live enforcement, completely unchanged - they're just
 * not rendered on this page for now (see
 * app/applications/config_schemas.py's module docstring on the backend
 * for the full rationale). The custom key/value extra-parameters editor
 * this screen used to have was removed in the 2026-09 follow-up 3 pass
 * ("Remove feature for parameters (key,value) from this section").
 *
 * Every save here has a REAL effect on the next request, not just
 * storage: default_gateway/PayU credentials/redirect URLs change the
 * very next payment, the webhook fields change the next delivery
 * attempt, and the SMTP/sender fields change the next email's transport
 * and From header.
 */
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  adminGetApplicationConfig,
  adminUpdateGeneralConfig,
  adminUpdateIntegrationConfig,
  adminUpdateNotificationConfig,
  adminUpdatePaymentGatewayConfig,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { RichTextEditor } from "../../components/RichTextEditor";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type {
  ApplicationConfigOut,
  ApplicationGeneralOut,
  EveryticketIntegrationOut,
  NotificationConfigOut,
  PaymentGatewayConfigOut,
} from "../../api/types";

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AUD", "CAD", "AED", "SGD"];

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="admin-panel">
      <h2>{title}</h2>
      {hint && <p className="hint">{hint}</p>}
      {children}
    </div>
  );
}

function SaveButton({ saving, savedAt }: { saving: boolean; savedAt: number | null }) {
  return (
    <>
      <button className="button button-primary" type="submit" disabled={saving}>
        {saving ? "Saving..." : "Save"}
      </button>
      {savedAt && <span className="hint" style={{ marginLeft: 8 }}>Saved.</span>}
    </>
  );
}

function GeneralSection({ initial, token }: { initial: ApplicationGeneralOut; token: string }) {
  const toast = useToast();
  const [name, setName] = useState(initial.name);
  const [currency, setCurrency] = useState(initial.currency);
  const [gatewayMode, setGatewayMode] = useState(initial.gateway_mode);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await adminUpdateGeneralConfig({ name, currency, gateway_mode: gatewayMode }, token);
      setSavedAt(Date.now());
      toast.success("Application configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section title="Application" hint="Application name, currency, and whether payments run in Live or Test mode.">
      <ErrorBanner error={error} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="inline-form">
          <label>
            Application name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Currency
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            Live / Test mode
            <select value={gatewayMode} onChange={(e) => setGatewayMode(e.target.value)}>
              <option value="test">Test</option>
              <option value="live">Live</option>
            </select>
          </label>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

function PaymentGatewaySection({ initial, token }: { initial: PaymentGatewayConfigOut; token: string }) {
  const toast = useToast();
  const [defaultGateway, setDefaultGateway] = useState(initial.default_gateway);
  const [returnUrl, setReturnUrl] = useState(initial.return_url ?? "");
  const [payuWebhookBaseUrl, setPayuWebhookBaseUrl] = useState(initial.payu_webhook_base_url ?? "");
  const [payuTestKey, setPayuTestKey] = useState("");
  const [payuTestSalt, setPayuTestSalt] = useState("");
  const [payuLiveKey, setPayuLiveKey] = useState("");
  const [payuLiveSalt, setPayuLiveSalt] = useState("");
  const [status, setStatus] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await adminUpdatePaymentGatewayConfig(
        {
          default_gateway: defaultGateway,
          return_url: returnUrl || null,
          payu_webhook_base_url: payuWebhookBaseUrl || null,
          payu_test:
            defaultGateway === "payu" && (payuTestKey || payuTestSalt)
              ? { merchant_key: payuTestKey || undefined, merchant_salt: payuTestSalt || undefined }
              : undefined,
          payu_live:
            defaultGateway === "payu" && (payuLiveKey || payuLiveSalt)
              ? { merchant_key: payuLiveKey || undefined, merchant_salt: payuLiveSalt || undefined }
              : undefined,
        },
        token,
      );
      setStatus(updated);
      setReturnUrl(updated.return_url ?? "");
      setPayuWebhookBaseUrl(updated.payu_webhook_base_url ?? "");
      setPayuTestKey("");
      setPayuTestSalt("");
      setPayuLiveKey("");
      setPayuLiveSalt("");
      setSavedAt(Date.now());
      toast.success("Payment gateway configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="Payment gateway"
      hint="Default gateway takes effect on the very next payment. Whether the Test or Live credentials below are actually used is decided by the Live/Test mode set in the Application section above."
    >
      <ErrorBanner error={error} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="inline-form">
          <label>
            Payment gateway
            <select value={defaultGateway} onChange={(e) => setDefaultGateway(e.target.value)}>
              {initial.available_gateways.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
        </div>

        <fieldset style={{ marginTop: 12 }}>
          <legend>Redirect &amp; webhook URLs</legend>
          <p className="hint">
            Both fall back to a local-development default (localhost) when left blank - set these for any real
            deployment.
          </p>
          <div className="inline-form">
            <label>
              Return URL
              <input
                value={returnUrl}
                onChange={(e) => setReturnUrl(e.target.value)}
                placeholder="https://subscribe.everyticket.com"
              />
              <span className="hint">Where the customer's browser lands after paying (and the SSO consume link).</span>
            </label>
            <label>
              PayU webhook URL
              <input
                value={payuWebhookBaseUrl}
                onChange={(e) => setPayuWebhookBaseUrl(e.target.value)}
                placeholder="https://api.everyticket.com"
              />
              <span className="hint">This backend's own public base URL - PayU calls back to it to confirm payment.</span>
            </label>
          </div>
        </fieldset>

        {defaultGateway === "payu" ? (
          <>
            <fieldset style={{ marginTop: 12 }}>
              <legend>PayU test credentials</legend>
              <div className="inline-form">
                <label>
                  Merchant key {status.payu_test.merchant_key_is_set && <span className="hint">(configured)</span>}
                  <input value={payuTestKey} onChange={(e) => setPayuTestKey(e.target.value)} placeholder="leave blank to keep current" />
                </label>
                <label>
                  Merchant salt {status.payu_test.merchant_salt_is_set && <span className="hint">(configured)</span>}
                  <input type="password" value={payuTestSalt} onChange={(e) => setPayuTestSalt(e.target.value)} placeholder="leave blank to keep current" />
                </label>
              </div>
            </fieldset>
            <fieldset style={{ marginTop: 12 }}>
              <legend>PayU live credentials</legend>
              <div className="inline-form">
                <label>
                  Merchant key {status.payu_live.merchant_key_is_set && <span className="hint">(configured)</span>}
                  <input value={payuLiveKey} onChange={(e) => setPayuLiveKey(e.target.value)} placeholder="leave blank to keep current" />
                </label>
                <label>
                  Merchant salt {status.payu_live.merchant_salt_is_set && <span className="hint">(configured)</span>}
                  <input type="password" value={payuLiveSalt} onChange={(e) => setPayuLiveSalt(e.target.value)} placeholder="leave blank to keep current" />
                </label>
              </div>
            </fieldset>
          </>
        ) : (
          <p className="hint">The mock gateway needs no credentials.</p>
        )}

        <div style={{ marginTop: 12 }}>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

function IntegrationSection({ initial, token }: { initial: EveryticketIntegrationOut; token: string }) {
  const toast = useToast();
  const [webhookUrl, setWebhookUrl] = useState(initial.webhook_url ?? "");
  const [secretKey, setSecretKey] = useState("");
  const [secretKeyIsSet, setSecretKeyIsSet] = useState(initial.secret_key_is_set);
  const [retryLimit, setRetryLimit] = useState(initial.retry_limit != null ? String(initial.retry_limit) : "");
  const [escalationEmails, setEscalationEmails] = useState(initial.escalation_emails ?? "");
  const [escalationSubject, setEscalationSubject] = useState(initial.escalation_email_subject ?? "");
  const [archiveAfterDays, setArchiveAfterDays] = useState(
    initial.archive_after_days != null ? String(initial.archive_after_days) : "",
  );
  const [webhookSamples, setWebhookSamples] = useState(initial.webhook_samples);
  const [editorKey] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const escalationBody = String(form.get("escalation_email_body") || "") || null;

    setSaving(true);
    setError(null);
    try {
      const updated = await adminUpdateIntegrationConfig(
        {
          webhook_url: webhookUrl || null,
          secret_key: secretKey || undefined,
          retry_limit: retryLimit ? Number(retryLimit) : null,
          escalation_emails: escalationEmails || null,
          escalation_email_subject: escalationSubject || null,
          escalation_email_body: escalationBody,
          archive_after_days: archiveAfterDays ? Number(archiveAfterDays) : null,
        },
        token,
      );
      setSecretKeyIsSet(updated.secret_key_is_set);
      setSecretKey("");
      setWebhookSamples(updated.webhook_samples);
      setSavedAt(Date.now());
      toast.success("Everyticket integration configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="Everyticket integration"
      hint="Webhook destination and retry limit take effect on the next webhook delivery attempt. If every retry fails, an escalation email is sent to the recipients below."
    >
      <ErrorBanner error={error} />
      <form onSubmit={handleSubmit}>
        <div className="inline-form">
          <label>
            Secret key {secretKeyIsSet && <span className="hint">(configured)</span>}
            <input type="password" value={secretKey} onChange={(e) => setSecretKey(e.target.value)} placeholder="leave blank to keep current" />
          </label>
          <label>
            Webhook URL
            <input value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="https://everyticket.example.com/webhooks/subscription" />
          </label>
          <label>
            Retry limit
            <input
              type="number"
              min="0"
              value={retryLimit}
              onChange={(e) => setRetryLimit(e.target.value)}
              placeholder={`default: ${initial.default_retry_limit}`}
            />
          </label>
          <label>
            Archive/delete after (days)
            <input
              type="number"
              min="0"
              value={archiveAfterDays}
              onChange={(e) => setArchiveAfterDays(e.target.value)}
              placeholder="disabled"
            />
            <span className="hint">
              Days an expired subscription can stay unrenewed before the archive webhook below fires. Blank disables
              archiving.
            </span>
          </label>
        </div>

        <h3 style={{ marginTop: 16 }}>Webhook events</h3>
        <p className="hint">
          Everyticket's endpoint receives exactly one of these five JSON bodies for the corresponding event. Save
          first to refresh the samples below with your latest settings.
        </p>
        <div className="webhook-sample-list">
          {webhookSamples.map((sample) => (
            <div className="webhook-sample" key={sample.event}>
              <div className="webhook-sample-header">
                <code>{sample.event}</code>
                <span className="hint">{sample.trigger}</span>
              </div>
              <pre className="webhook-sample-body">{JSON.stringify(sample.payload, null, 2)}</pre>
            </div>
          ))}
        </div>

        <h3 style={{ marginTop: 16 }}>If all retries fail</h3>
        <div className="inline-form">
          <label>
            Notify email(s)
            <input
              value={escalationEmails}
              onChange={(e) => setEscalationEmails(e.target.value)}
              placeholder="ops@example.com, billing@example.com"
            />
          </label>
          <label>
            Email subject
            <input value={escalationSubject} onChange={(e) => setEscalationSubject(e.target.value)} placeholder="Webhook delivery failed" />
          </label>
        </div>
        <label>
          Email content
          <RichTextEditor
            key={editorKey}
            name="escalation_email_body"
            defaultValue={initial.escalation_email_body}
            placeholder="A webhook delivery has failed after all retries..."
          />
        </label>

        <div style={{ marginTop: 12 }}>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

function NotificationSection({ initial, token }: { initial: NotificationConfigOut; token: string }) {
  const toast = useToast();
  const [smtpHost, setSmtpHost] = useState(initial.smtp_host ?? "");
  const [smtpPort, setSmtpPort] = useState(initial.smtp_port != null ? String(initial.smtp_port) : "");
  const [smtpUsername, setSmtpUsername] = useState(initial.smtp_username ?? "");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpPasswordIsSet, setSmtpPasswordIsSet] = useState(initial.smtp_password_is_set);
  const [smtpUseTls, setSmtpUseTls] = useState(initial.smtp_use_tls ?? false);
  const [senderName, setSenderName] = useState(initial.email_sender_name ?? "");
  const [senderAddress, setSenderAddress] = useState(initial.email_sender_address ?? "");
  const [replyTo, setReplyTo] = useState(initial.email_reply_to ?? "");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await adminUpdateNotificationConfig(
        {
          email_provider: "smtp",
          smtp_host: smtpHost || null,
          smtp_port: smtpPort ? Number(smtpPort) : null,
          smtp_username: smtpUsername || null,
          smtp_password: smtpPassword || undefined,
          smtp_use_tls: smtpUseTls,
          email_sender_name: senderName || null,
          email_sender_address: senderAddress || null,
          email_reply_to: replyTo || null,
        },
        token,
      );
      setSmtpPasswordIsSet(updated.smtp_password_is_set);
      setSmtpPassword("");
      setSavedAt(Date.now());
      toast.success("Notification configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="Notifications"
      hint="SMTP transport and sender overrides for every email this application sends, falling back to the backend-wide default for any field left blank."
    >
      <ErrorBanner error={error} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="inline-form">
          <label>
            SMTP host
            <input value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} placeholder="smtp.example.com" />
          </label>
          <label>
            SMTP port
            <input type="number" value={smtpPort} onChange={(e) => setSmtpPort(e.target.value)} placeholder="587" />
          </label>
          <label>
            SMTP username
            <input value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)} />
          </label>
          <label>
            SMTP password {smtpPasswordIsSet && <span className="hint">(configured)</span>}
            <input type="password" value={smtpPassword} onChange={(e) => setSmtpPassword(e.target.value)} placeholder="leave blank to keep current" />
          </label>
          <label>
            Use TLS
            <input type="checkbox" checked={smtpUseTls} onChange={(e) => setSmtpUseTls(e.target.checked)} />
          </label>
          <label>
            Sender name
            <input value={senderName} onChange={(e) => setSenderName(e.target.value)} placeholder="Everyticket Subscriptions" />
          </label>
          <label>
            Sender address
            <input value={senderAddress} onChange={(e) => setSenderAddress(e.target.value)} placeholder="no-reply@example.com" />
          </label>
          <label>
            Reply-to
            <input value={replyTo} onChange={(e) => setReplyTo(e.target.value)} placeholder="support@example.com" />
          </label>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

export function AdminConfigPage() {
  const { adminToken } = useAuth();
  const [config, setConfig] = useState<ApplicationConfigOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetApplicationConfig(adminToken).then(setConfig).catch(setError);
  }, [adminToken]);

  return (
    <section>
      <h1>Configuration</h1>
      <ErrorBanner error={error} />
      {config === null && !error && <p>Loading...</p>}
      {config && adminToken && (
        <>
          <GeneralSection initial={config.general} token={adminToken} />
          <PaymentGatewaySection initial={config.payment_gateway} token={adminToken} />
          <IntegrationSection initial={config.integration} token={adminToken} />
          <NotificationSection initial={config.notification} token={adminToken} />
        </>
      )}
    </section>
  );
}
