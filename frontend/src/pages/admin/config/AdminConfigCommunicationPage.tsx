/**
 * Configuration -> Communication (2026-09-14 follow-up: "Under
 * Configuration, 4 sub menu will come - 3. Communication - will contain
 * Notification section from config (Email section)"). Same SMTP
 * transport + sender-override form previously called "Notifications"
 * inside the single stacked Configuration screen, on its own route/
 * sidebar entry - unchanged behavior, just relocated. Not to be confused
 * with the separate "Notifications" page under the Communications
 * sidebar group (email templates + delivery logs) - this is the SMTP/
 * sender configuration form only.
 */
import { ErrorBanner } from "../../../components/ErrorBanner";
import { NotificationSection } from "./ConfigSections";
import { useApplicationConfig } from "./useApplicationConfig";

export function AdminConfigCommunicationPage() {
  const { config, error, adminToken } = useApplicationConfig();

  return (
    <section>
      <h1>Configuration - Communication</h1>
      <ErrorBanner error={error} />
      {config === null && !error && <p>Loading...</p>}
      {config && adminToken && <NotificationSection initial={config.notification} token={adminToken} />}
    </section>
  );
}
