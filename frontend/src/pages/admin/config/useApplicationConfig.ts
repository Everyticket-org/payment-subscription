/**
 * Shared fetch used by every Configuration sub-page (General, Payment
 * gateway, Communication, Integration - 2026-09-14 follow-up: "Under
 * Configuration, 4 sub menu will come"). All four sections come back
 * together in one GET /api/v1/admin/config/application response, so each
 * page independently re-fetches the whole thing and renders only its own
 * slice - the same per-page-independent-fetch pattern every other admin
 * page in this app already uses (AdminPlansPage, AdminCustomersPage,
 * ...), rather than introducing a shared route layout/context that would
 * be the only one of its kind in this codebase.
 */
import { useEffect, useState } from "react";
import { adminGetApplicationConfig } from "../../../api/endpoints";
import { useAuth } from "../../../context/AuthContext";
import type { ApplicationConfigOut } from "../../../api/types";

export function useApplicationConfig() {
  const { adminToken } = useAuth();
  const [config, setConfig] = useState<ApplicationConfigOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetApplicationConfig(adminToken).then(setConfig).catch(setError);
  }, [adminToken]);

  return { config, error, adminToken };
}
