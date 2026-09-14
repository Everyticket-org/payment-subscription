/**
 * Configuration -> Integration (2026-09-14 follow-up: "Under
 * Configuration, 4 sub menu will come - 4. Integration - will be
 * Everyticket Integration"). Same secret key/webhook URL/retry limit/
 * archive-after-days/webhook-fields/escalation-email form this screen
 * has always had, on its own route/sidebar entry.
 */
import { ErrorBanner } from "../../../components/ErrorBanner";
import { IntegrationSection } from "./ConfigSections";
import { useApplicationConfig } from "./useApplicationConfig";

export function AdminConfigIntegrationPage() {
  const { config, error, adminToken } = useApplicationConfig();

  return (
    <section>
      <h1>Configuration - Integration</h1>
      <ErrorBanner error={error} />
      {config === null && !error && <p>Loading...</p>}
      {config && adminToken && <IntegrationSection initial={config.integration} token={adminToken} />}
    </section>
  );
}
