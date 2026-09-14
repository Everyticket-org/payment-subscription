/**
 * Configuration -> Payment Gateway (2026-09-14 follow-up: "Under
 * Configuration, 4 sub menu will come - 2. Payment Gateway - will
 * contain payment gateway config"). Same gateway dropdown + per-mode
 * PayU credentials + redirect/webhook URL form this screen has always
 * had, on its own route/sidebar entry.
 */
import { ErrorBanner } from "../../../components/ErrorBanner";
import { PaymentGatewaySection } from "./ConfigSections";
import { useApplicationConfig } from "./useApplicationConfig";

export function AdminConfigPaymentGatewayPage() {
  const { config, error, adminToken } = useApplicationConfig();

  return (
    <section>
      <h1>Configuration - Payment Gateway</h1>
      <ErrorBanner error={error} />
      {config === null && !error && <p>Loading...</p>}
      {config && adminToken && <PaymentGatewaySection initial={config.payment_gateway} token={adminToken} />}
    </section>
  );
}
