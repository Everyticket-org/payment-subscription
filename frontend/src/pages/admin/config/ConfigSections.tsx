/**
 * The four Configuration section forms - Application (General), Payment
 * gateway, Everyticket Integration, and Notifications (Communication) -
 * factored out of what used to be a single stacked AdminConfigPage.tsx
 * screen (see docs/implementation-status.md's 2026-09 entries for that
 * screen's own history) so each can now live on its own route/sidebar
 * entry (2026-09-14 follow-up: "Under Configuration, 4 sub menu will
 * come - 1. General... 2. Payment Gateway... 3. Communication... 4.
 * Integration"). Nothing about any section's own behavior changed in
 * that split - each still POSTs/PUTs to exactly the endpoint it always
 * has and every save here still has a REAL effect on the next request,
 * not just storage: default_gateway/PayU credentials/redirect URLs
 * change the very next payment, the webhook fields change the next
 * delivery attempt, and the SMTP/sender fields change the next email's
 * transport and From header. "Subscription rules" and "Security"
 * configuration keep their existing backend endpoints and live
 * enforcement, completely unchanged - they're just not rendered by any
 * of these four pages (see app/applications/config_schemas.py's module
 * docstring on the backend for the full rationale).
 */
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  adminUpdateGeneralConfig,
  adminUpdateIntegrationConfig,
  adminUpdateNotificationConfig,
  adminUpdatePaymentGatewayConfig,
} from "../../../api/endpoints";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { RichTextEditor } from "../../../components/RichTextEditor";
import { useToast } from "../../../context/ToastContext";
import type {
  ApplicationGeneralOut,
  EveryticketIntegrationOut,
  NotificationConfigOut,
  PaymentGatewayConfigOut,
} from "../../../api/types";

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AUD", "CAD", "AED", "SGD"];

export function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="admin-panel">
      <h2>{title}</h2>
      {hint && <p className="hint">{hint}</p>}
      {children}
    </div>
  );
}

export function SaveButton({ saving, savedAt }: { saving: boolean; savedAt: number | null }) {
  return (
    <>
      <button className="button button-primary" type="submit" disabled={saving}>
        {saving ? "Saving..." : "Save"}
      </button>
      {savedAt && <span className="hint" style={{ marginLeft: 8 }}>Saved.</span>}
    </>
  );
}

export function GeneralSection({ initial, token }: { initial: ApplicationGeneralOut; token: string }) {
  const toast = useToast();
  const [name, setName] = useState(initial.name);
  const [currency, setCurrency] = useState(initial.currency);
  const [gatewayMode, setGatewayMode] = useState(initial.gateway_mode);
  const [postSubscriptionMessage, setPostSubscriptionMessage] = useState(initial.post_subscription_message ?? "");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await adminUpdateGeneralConfig(
        { name, currency, gateway_mode: gatewayMode, post_subscription_message: postSubscriptionMessage || null },
        token,
      );
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
        </div>
        <label style={{ display: "block", marginTop: 12 }}>
          Post-subscription message
          <textarea
            rows={2}
            value={postSubscriptionMessage}
            onChange={(e) => setPostSubscriptionMessage(e.target.value)}
            placeholder="You have successfully subscribed, you will get your credentials in sometime."
            style={{ width: "100%" }}
          />
        </label>
        <p className="hint">
          Shown on the thank-you screen after a brand-new customer's first payment succeeds (never for an existing
          customer renewing or changing plans - they already have their credentials). Leave blank to use the default
          text above.
        </p>
        <SaveButton saving={saving} savedAt={savedAt} />
      </form>
    </Section>
  );
}

export function PaymentGatewaySection({ initial, token }: { initial: PaymentGatewayConfigOut; token: string }) {
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
      hint="Default gateway takes effect on the very next payment. Whether the Test or Live credentials below are actually used is decided by the Live/Test mode set in the General section."
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

export function IntegrationSection({ initial, token }: { initial: EveryticketIntegrationOut; token: string }) {
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
  // 2026-09-14 follow-up 3: "when select checkbox for parameters, it
  // should reflect into sample JSON as well" - webhook_samples_all_fields
  // carries every optional field's real sample value for every event (as
  // if all were selected); livePreviewSample below (declared after
  // fieldSelection/fieldCatalog) filters it down to whatever's currently
  // ticked so the JSON on the right updates the instant a checkbox
  // changes, with no round trip and no Save needed. This fully replaces
  // the plain webhook_samples field for display purposes - the initial
  // render's live preview reproduces webhook_samples exactly, since
  // fieldSelection starts out equal to the saved selection.
  const [samplesAllFields, setSamplesAllFields] = useState(initial.webhook_samples_all_fields);
  // 2026-09-14 follow-up: "allow to configure, more data to be passed for
  // webhook call like plan details including name, amount, expiry etc.."
  // fieldCatalog (optional, tickable fields) and fixedFields (always-sent
  // fields, display-only - 2026-09-14 follow-up 2: "activated does not
  // have plan name, code, price... where it has to be... keep
  // consistency", so both groups are now shown together for every event)
  // are code-level catalogs, not application data, so neither needs its
  // own setter; fieldSelection is this application's current per-event
  // choice, editable via the checkboxes below and saved along with
  // everything else on this form.
  const [fieldCatalog] = useState(initial.webhook_field_catalog);
  const [fixedFields] = useState(initial.webhook_fixed_fields);
  const [fieldSelection, setFieldSelection] = useState<Record<string, string[]>>(initial.webhook_field_selection);
  const eventTypes = Object.keys(fieldCatalog);
  // 2026-09-14 follow-up 3: "Give dropdown - when eventtype selected, it
  // will show checklist left side and sample JSON at right side so we
  // can reduce overall space" - one event's fields+sample shown at a
  // time instead of all seven stacked, cutting this screen's height a
  // lot.
  const [selectedEventType, setSelectedEventType] = useState(eventTypes[0]);
  // 2026-09-14 follow-up 3: "when select checkbox for parameters, it should
  // reflect into sample JSON as well" - recomputed on every render a
  // checkbox changes (fieldSelection is a dependency), so the JSON on the
  // right updates the instant a box is ticked, before Save. This never
  // invents a value: it starts from samplesAllFields' real, backend-computed
  // wire body (as if every optional field were selected) and only decides,
  // per key, whether to show or hide it - a fixed field or any key outside
  // the optional catalog (e.g. dynamic registration-data fields) is always
  // kept, and an optional field is kept only while its checkbox is ticked.
  // Note: sample.payload is the whole {event_type, payload: {...}} wire
  // body (see build_webhook_samples), so the actual field keys to filter
  // live one level down, inside that nested "payload" object - not on
  // sample.payload itself.
  const livePreviewSample = useMemo(() => {
    const sample = samplesAllFields.find((s) => s.event === selectedEventType);
    if (!sample) return null;
    const wireBody = sample.payload as { payload?: Record<string, unknown> };
    const innerAll = wireBody.payload ?? {};
    const optionalFields = new Set((fieldCatalog[selectedEventType] ?? []).map((entry) => entry.field));
    const selected = new Set(fieldSelection[selectedEventType] ?? []);
    const innerFiltered: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(innerAll)) {
      if (optionalFields.has(key) && !selected.has(key)) continue;
      innerFiltered[key] = value;
    }
    return { ...sample, payload: { ...wireBody, payload: innerFiltered } };
  }, [samplesAllFields, selectedEventType, fieldCatalog, fieldSelection]);
  const [editorKey] = useState(() => Date.now());
  // 2026-09-13 follow-up 3: credentials Everyticket's own backend sends
  // as X-Api-Key/X-Api-Secret headers when it calls POST /api/v1/
  // integration/sso/generate-link - unlike secret_key (internal, admin
  // types it once and forgets it), apiSecret is deliberately a plain
  // text field, not password-masked: the admin's whole job here is to
  // copy this value and hand it to Everyticket's team out of band, so
  // hiding it on screen would be actively unhelpful.
  const [apiKey, setApiKey] = useState(initial.api_key ?? "");
  const [apiSecret, setApiSecret] = useState("");
  const [apiSecretIsSet, setApiSecretIsSet] = useState(initial.api_secret_is_set);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  function toggleWebhookField(eventType: string, field: string) {
    setFieldSelection((prev) => {
      const current = prev[eventType] ?? [];
      const next = current.includes(field) ? current.filter((f) => f !== field) : [...current, field];
      return { ...prev, [eventType]: next };
    });
  }

  function handleGenerateApiCredentials() {
    const randomToken = (bytes: number) =>
      Array.from(crypto.getRandomValues(new Uint8Array(bytes)))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");
    setApiKey(`et-${randomToken(12)}`);
    setApiSecret(randomToken(32));
  }

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
          webhook_field_selection: fieldSelection,
          api_key: apiKey || "",
          api_secret: apiSecret || undefined,
        },
        token,
      );
      setSecretKeyIsSet(updated.secret_key_is_set);
      setSecretKey("");
      setApiKey(updated.api_key ?? "");
      setApiSecretIsSet(updated.api_secret_is_set);
      setSamplesAllFields(updated.webhook_samples_all_fields);
      setFieldSelection(updated.webhook_field_selection);
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

        <h3 style={{ marginTop: 16 }}>SSO API access (for Everyticket's "Manage Subscription" link)</h3>
        <p className="hint">
          Everyticket's own backend calls <code>POST /api/v1/integration/sso/generate-link</code> with these two
          values (as <code>X-Api-Key</code> / <code>X-Api-Secret</code> headers) to mint a one-time login link for a
          customer, so clicking "Manage Subscription" inside Everyticket signs them straight into this portal - no
          second password. Generate a pair below, save, then share both values with Everyticket's integration team
          out of band (the same way as the secret key above) - this app never sends them anywhere itself.
        </p>
        <div className="inline-form">
          <label>
            API key
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="not configured" />
          </label>
          <label>
            API secret {apiSecretIsSet && !apiSecret && <span className="hint">(configured, hidden)</span>}
            <input
              value={apiSecret}
              onChange={(e) => setApiSecret(e.target.value)}
              placeholder="leave blank to keep current"
            />
          </label>
          <button type="button" className="button button-secondary" onClick={handleGenerateApiCredentials}>
            Generate random values
          </button>
        </div>
        {apiSecret && (
          <p className="hint hint-dev">
            Copy this API secret now - after you save, it's stored but never shown again in full.
          </p>
        )}
        {/* 2026-09-14 follow-up: "What parameters Everyticket has to send
            apart from key and secret... please show json as help text" -
            the key/secret above only authenticate the call (as headers);
            this is the full request/response contract for the call
            itself, straight from app.sso.schemas.SsoLinkGenerateRequest/
            SsoLinkOut and app.api.v1.integration.generate_sso_link - kept
            here so it can be handed to Everyticket's integration team
            alongside the credentials without them needing the backend
            source. */}
        <div className="webhook-sample" style={{ marginTop: 12, maxWidth: 560 }}>
          <div className="webhook-sample-header">
            <code>POST /api/v1/integration/sso/generate-link</code>
          </div>
          <pre className="webhook-sample-body">
            {JSON.stringify(
              {
                headers: {
                  "X-Api-Key": "<the API key above>",
                  "X-Api-Secret": "<the API secret above>",
                },
                body: {
                  external_customer_id: "ET-CUST-10432",
                  user_identifier: "admin-42",
                },
                response: {
                  sso_token: "eyJhbGciOi...",
                  consume_url: "https://subscribe.everyticket.com/sso/consume?token=eyJhbGciOi...",
                  expires_at: "2026-09-14T07:15:00+00:00",
                },
              },
              null,
              2,
            )}
          </pre>
        </div>
        <p className="hint">
          <code>external_customer_id</code> (required) is the same value Everyticket's own backend already
          returned when it responded to the subscription.activated webhook (its success/external_customer_id/
          instance_id reply), so it's always on hand by the time a customer clicks "Manage Subscription".{" "}
          <code>user_identifier</code> is optional, free-form context (e.g. which of Everyticket's own admin
          users triggered this) stored for audit only and never interpreted by this app. Everyticket's app then
          just opens the returned <code>consume_url</code> - the customer lands signed in, no second password.
        </p>

        <h3 style={{ marginTop: 16 }}>Webhook events</h3>
        <p className="hint">
          Pick an event to see exactly what it sends: fields marked "always sent" are on every delivery already;
          tick any of the rest to have Everyticket receive those too - e.g. tick "Plan price" and "Subscription
          expiry date/time" for Renew so it gets those without a separate lookup. The sample JSON on the right
          updates instantly as you tick boxes; Save to make the change take effect on the next real delivery.
        </p>
        <label className="webhook-event-picker">
          Event
          <select value={selectedEventType} onChange={(e) => setSelectedEventType(e.target.value)}>
            {eventTypes.map((eventType) => (
              <option key={eventType} value={eventType}>
                {eventType}
              </option>
            ))}
          </select>
        </label>
        <div className="webhook-event-detail">
          <div className="webhook-field-event">
            <div className="webhook-field-checklist">
              {fixedFields[selectedEventType]?.map((entry) => (
                <label key={`fixed-${entry.field}`} className="webhook-field-checkbox webhook-field-checkbox-fixed">
                  <input type="checkbox" checked disabled />
                  <span>
                    {entry.label} <span className="hint">(always sent)</span>
                  </span>
                </label>
              ))}
              {fieldCatalog[selectedEventType]?.map((entry) => (
                <label key={entry.field} className="webhook-field-checkbox">
                  <input
                    type="checkbox"
                    checked={(fieldSelection[selectedEventType] ?? []).includes(entry.field)}
                    onChange={() => toggleWebhookField(selectedEventType, entry.field)}
                  />
                  <span>{entry.label}</span>
                </label>
              ))}
            </div>
          </div>
          {livePreviewSample && (
            <div className="webhook-sample" key={livePreviewSample.event}>
              <div className="webhook-sample-header">
                <code>{livePreviewSample.event}</code>
                <span className="hint">{livePreviewSample.trigger}</span>
              </div>
              <pre className="webhook-sample-body">{JSON.stringify(livePreviewSample.payload, null, 2)}</pre>
            </div>
          )}
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

export function NotificationSection({ initial, token }: { initial: NotificationConfigOut; token: string }) {
  const toast = useToast();
  const [notificationsEnabled, setNotificationsEnabled] = useState(initial.notifications_enabled);
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
          notifications_enabled: notificationsEnabled,
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
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={notificationsEnabled}
            onChange={(e) => setNotificationsEnabled(e.target.checked)}
          />
          Enable Notifications?
        </label>
        <p className="hint">
          When off, every email this application would send (OTP, payment/invoice confirmations, renewal
          reminders, webhook-failure escalation, Test Email, ...) is skipped and logged as SKIPPED in
          Notification Logs, regardless of how the SMTP settings below are configured.
        </p>
        <div className="inline-form" style={notificationsEnabled ? undefined : { opacity: 0.5, pointerEvents: "none" }}>
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
        </div>
        <SaveButton saving={saving} savedAt={savedAt} />
      </form>
    </Section>
  );
}
