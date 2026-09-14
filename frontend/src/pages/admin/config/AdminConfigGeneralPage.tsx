/**
 * Configuration -> General (2026-09-14 follow-up: "Under Configuration, 4
 * sub menu will come - 1. General - which contains application"). Same
 * Application name/currency/Live-Test-Mode/post-subscription-message
 * form this screen has always had - just on its own route and sidebar
 * entry now instead of stacked with the other three Configuration
 * sections (see docs/implementation-status.md for that history).
 */
import { ErrorBanner } from "../../../components/ErrorBanner";
import { GeneralSection } from "./ConfigSections";
import { useApplicationConfig } from "./useApplicationConfig";

export function AdminConfigGeneralPage() {
  const { config, error, adminToken } = useApplicationConfig();

  return (
    <section>
      <h1>Configuration - General</h1>
      <ErrorBanner error={error} />
      {config === null && !error && <p>Loading...</p>}
      {config && adminToken && <GeneralSection initial={config.general} token={adminToken} />}
    </section>
  );
}
