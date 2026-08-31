/**
 * Admin configuration screens (spec sections 13, 51, 81): Payment
 * Gateway Configuration, Everyticket Integration Configuration,
 * Notification Configuration, Security Configuration, and System
 * Configuration all live on this one page, one section per screen -
 * they're all small field groups of the same single V1 application (or,
 * for Security, a handful of OTP tunables), so five separate pages would
 * just be five thin wrappers around one form each.
 *
 * Every save here has a REAL effect on the next request, not just
 * storage: default_gateway changes which gateway the next payment uses,
 * the notification sender fields change the next email's From header,
 * the subscription-rule toggles actually 403 the corresponding customer
 * action, and the security fields actually change the next OTP issued.
 */
import { useEffect, useState, type ReactNode } from "react";
import {
  adminGetApplicationConfig,
  adminGetSecurityConfig,
  adminUpdateGeneralConfig,
  adminUpdateIntegrationConfig,
  adminUpdateNotificationConfig,
  adminUpdatePaymentConfig,
  adminUpdateSecurityConfig,
  adminUpdateSubscriptionRulesConfig,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type {
  ApplicationConfigOut,
  ApplicationGeneralOut,
  ApplicationIntegrationOut,
  ApplicationNotificationOut,
  ApplicationPaymentOut,
  ApplicationSubscriptionRulesOut,
  SecurityConfigOut,
} from "../../api/types";

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
  const [url, setUrl] = useState(initial.application_url);
  const [supportEmail, setSupportEmail] = useState(initial.support_email ?? "");
  const [supportPhone, setSupportPhone] = useState(initial.support_phone ?? "");
  const [timezone, setTimezone] = useState(initial.timezone);
  const [currency, setCurrency] = useState(initial.currency);
  const [active, setActive] = useState(initial.active);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await adminUpdateGeneralConfig(
        {
          name,
          application_url: url,
          support_email: supportEmail || null,
          support_phone: supportPhone || null,
          timezone,
          currency,
          active,
        },
        token,
      );
      setSavedAt(Date.now());
      toast.success("System configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section title="System configuration" hint="Application name, URL, support contact, timezone, and currency.">
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
            Application URL
            <input value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <label>
            Support email
            <input value={supportEmail} onChange={(e) => setSupportEmail(e.target.value)} />
          </label>
          <label>
            Support phone
            <input value={supportPhone} onChange={(e) => setSupportPhone(e.target.value)} />
          </label>
          <label>
            Timezone
            <input value={timezone} onChange={(e) => setTimezone(e.target.value)} />
          </label>
          <label>
            Currency
            <input value={currency} onChange={(e) => setCurrency(e.target.value)} />
          </label>
          <label>
            Active
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          </label>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

function IntegrationSection({ initial, token }: { initial: ApplicationIntegrationOut; token: string }) {
  const toast = useToast();
  const [apiUrl, setApiUrl] = useState(initial.api_url ?? "");
  const [webhookUrl, setWebhookUrl] = useState(initial.webhook_url ?? "");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [ssoSecret, setSsoSecret] = useState("");
  const [webhookSecretIsSet, setWebhookSecretIsSet] = useState(initial.webhook_secret_is_set);
  const [ssoSecretIsSet, setSsoSecretIsSet] = useState(initial.sso_secret_is_set);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await adminUpdateIntegrationConfig(
        {
          api_url: apiUrl || null,
          webhook_url: webhookUrl || null,
          // Leave secrets untouched unless the admin actually typed a new one.
          webhook_secret: webhookSecret || undefined,
          sso_secret: ssoSecret || undefined,
        },
        token,
      );
      setWebhookSecretIsSet(updated.webhook_secret_is_set);
      setSsoSecretIsSet(updated.sso_secret_is_set);
      setWebhookSecret("");
      setSsoSecret("");
      setSavedAt(Date.now());
      toast.success("Integration configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="Everyticket integration configuration"
      hint="Webhook destination + SSO secret already take effect on the next webhook delivery / SSO token. Secrets are never shown once saved - leave a field blank to keep the current value."
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
            Everyticket API URL
            <input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://everyticket.example.com/api" />
          </label>
          <label>
            Webhook URL
            <input value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="https://everyticket.example.com/webhooks/subscription" />
          </label>
          <label>
            Webhook secret {webhookSecretIsSet && <span className="hint">(configured)</span>}
            <input type="password" value={webhookSecret} onChange={(e) => setWebhookSecret(e.target.value)} placeholder="leave blank to keep current" />
          </label>
          <label>
            SSO secret {ssoSecretIsSet && <span className="hint">(configured)</span>}
            <input type="password" value={ssoSecret} onChange={(e) => setSsoSecret(e.target.value)} placeholder="leave blank to keep current" />
          </label>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

function PaymentSection({ initial, token }: { initial: ApplicationPaymentOut; token: string }) {
  const toast = useToast();
  const [defaultGateway, setDefaultGateway] = useState(initial.default_gateway);
  const [gatewayMode, setGatewayMode] = useState(initial.gateway_mode);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await adminUpdatePaymentConfig({ default_gateway: defaultGateway, gateway_mode: gatewayMode }, token);
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
      title="Payment gateway configuration"
      hint="Default gateway takes effect on the very next payment. Gateway credentials (e.g. PayU's merchant key/salt) stay configured only in the backend's .env for security - not editable here."
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
            Default gateway
            <select value={defaultGateway} onChange={(e) => setDefaultGateway(e.target.value)}>
              <option value="mock">mock</option>
              <option value="payu">payu</option>
            </select>
          </label>
          <label>
            Gateway mode
            <select value={gatewayMode} onChange={(e) => setGatewayMode(e.target.value)}>
              <option value="test">test</option>
              <option value="live">live</option>
            </select>
          </label>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

function NotificationSection({ initial, token }: { initial: ApplicationNotificationOut; token: string }) {
  const toast = useToast();
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
      await adminUpdateNotificationConfig(
        {
          email_provider: "smtp",
          email_sender_name: senderName || null,
          email_sender_address: senderAddress || null,
          email_reply_to: replyTo || null,
        },
        token,
      );
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
      title="Notification configuration"
      hint="Overrides the sender name/address/reply-to on every email this application sends, falling back to the backend-wide default for any field left blank."
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

function SubscriptionRulesSection({ initial, token }: { initial: ApplicationSubscriptionRulesOut; token: string }) {
  const toast = useToast();
  const [allowUpgrade, setAllowUpgrade] = useState(initial.allow_upgrade);
  const [allowDowngrade, setAllowDowngrade] = useState(initial.allow_downgrade);
  const [allowCancellation, setAllowCancellation] = useState(initial.allow_cancellation);
  const [renewalEnabled, setRenewalEnabled] = useState(initial.renewal_enabled);
  const [repurchaseEnabled, setRepurchaseEnabled] = useState(initial.repurchase_enabled);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await adminUpdateSubscriptionRulesConfig(
        {
          allow_upgrade: allowUpgrade,
          allow_downgrade: allowDowngrade,
          allow_cancellation: allowCancellation,
          cancellation_behavior: "IMMEDIATE",
          renewal_enabled: renewalEnabled,
          repurchase_enabled: repurchaseEnabled,
        },
        token,
      );
      setSavedAt(Date.now());
      toast.success("Subscription rules saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      title="Subscription rules"
      hint="Upgrade/downgrade/cancellation/renewal toggles are enforced live - disabling one 403s the matching customer-portal action immediately. Cancellation is always IMMEDIATE (no alternate behavior in this build) and repurchase after expiry/cancellation is always allowed regardless of this toggle."
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
            Allow upgrade
            <input type="checkbox" checked={allowUpgrade} onChange={(e) => setAllowUpgrade(e.target.checked)} />
          </label>
          <label>
            Allow downgrade
            <input type="checkbox" checked={allowDowngrade} onChange={(e) => setAllowDowngrade(e.target.checked)} />
          </label>
          <label>
            Allow cancellation
            <input type="checkbox" checked={allowCancellation} onChange={(e) => setAllowCancellation(e.target.checked)} />
          </label>
          <label>
            Renewal enabled
            <input type="checkbox" checked={renewalEnabled} onChange={(e) => setRenewalEnabled(e.target.checked)} />
          </label>
          <label>
            Repurchase enabled
            <input type="checkbox" checked={repurchaseEnabled} onChange={(e) => setRepurchaseEnabled(e.target.checked)} />
          </label>
          <SaveButton saving={saving} savedAt={savedAt} />
        </div>
      </form>
    </Section>
  );
}

function SecuritySection({ initial, token }: { initial: SecurityConfigOut; token: string }) {
  const toast = useToast();
  const [otpLength, setOtpLength] = useState(String(initial.otp_length));
  const [otpExpiry, setOtpExpiry] = useState(String(initial.otp_expiry_seconds));
  const [otpMaxAttempts, setOtpMaxAttempts] = useState(String(initial.otp_max_attempts));
  const [otpCooldown, setOtpCooldown] = useState(String(initial.otp_resend_cooldown_seconds));
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await adminUpdateSecurityConfig(
        {
          otp_length: Number(otpLength),
          otp_expiry_seconds: Number(otpExpiry),
          otp_max_attempts: Number(otpMaxAttempts),
          otp_resend_cooldown_seconds: Number(otpCooldown),
        },
        token,
      );
      setSavedAt(Date.now());
      toast.success("Security configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section title="Security configuration" hint="Admin-tunable OTP parameters - takes effect on the next OTP issued.">
      <ErrorBanner error={error} />
      <p className="hint">
        Current safety-switch status (read-only here - change via the Testing tools page):{" "}
        <strong>TEST MODE {initial.test_mode ? "on" : "off"}</strong>,{" "}
        <strong>OTP bypass {initial.allow_otp_bypass ? "on" : "off"}</strong>,{" "}
        <strong>admin MFA bypass {initial.allow_admin_mfa_bypass ? "on" : "off"}</strong>.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <div className="inline-form">
          <label>
            OTP length
            <input type="number" min="4" max="10" value={otpLength} onChange={(e) => setOtpLength(e.target.value)} />
          </label>
          <label>
            OTP expiry (seconds)
            <input type="number" min="30" max="3600" value={otpExpiry} onChange={(e) => setOtpExpiry(e.target.value)} />
          </label>
          <label>
            Max verify attempts
            <input type="number" min="1" max="20" value={otpMaxAttempts} onChange={(e) => setOtpMaxAttempts(e.target.value)} />
          </label>
          <label>
            Resend cooldown (seconds)
            <input type="number" min="0" max="3600" value={otpCooldown} onChange={(e) => setOtpCooldown(e.target.value)} />
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
  const [security, setSecurity] = useState<SecurityConfigOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    Promise.all([adminGetApplicationConfig(adminToken), adminGetSecurityConfig(adminToken)])
      .then(([cfg, sec]) => {
        setConfig(cfg);
        setSecurity(sec);
      })
      .catch(setError);
  }, [adminToken]);

  return (
    <section>
      <h1>Configuration</h1>
      <ErrorBanner error={error} />
      {config === null && security === null && !error && <p>Loading...</p>}
      {config && security && adminToken && (
        <>
          <GeneralSection initial={config.general} token={adminToken} />
          <IntegrationSection initial={config.integration} token={adminToken} />
          <PaymentSection initial={config.payment} token={adminToken} />
          <NotificationSection initial={config.notification} token={adminToken} />
          <SubscriptionRulesSection initial={config.subscription_rules} token={adminToken} />
          <SecuritySection initial={security} token={adminToken} />
        </>
      )}
    </section>
  );
}
