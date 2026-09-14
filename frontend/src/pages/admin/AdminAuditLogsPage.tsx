/** Admin Audit Logs (spec section 56, 51) - read-only, append-only trail
 * of every admin mutation (plan changes, customer suspend/activate,
 * webhook retries, template edits, MFA bypass). */
import { Fragment, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { adminListAuditLogs } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Pagination } from "../../components/Pagination";
import { useAuth } from "../../context/AuthContext";
import { parsePageLimit } from "../../utils/pagination";
import type { AuditLogOut, PageOut } from "../../api/types";

export function AdminAuditLogsPage() {
  const { adminToken } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<PageOut<AuditLogOut> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const action = searchParams.get("action") ?? "";
  const entityType = searchParams.get("entity_type") ?? "";
  const limit = parsePageLimit(searchParams.get("limit"));
  const offset = Number(searchParams.get("offset") ?? "0");

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListAuditLogs(
      { action: action || undefined, entity_type: entityType || undefined, limit, offset },
      adminToken,
    )
      .then(setPage)
      .catch(setError);
  }, [adminToken, action, entityType, limit, offset]);

  useEffect(reload, [reload]);

  return (
    <section>
      <h1>Audit logs</h1>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <div className="admin-toolbar">
          <label>
            Action
            <input
              defaultValue={action}
              placeholder="e.g. PLAN_UPDATED"
              onBlur={(e) => setSearchParams({ action: e.target.value, entity_type: entityType, limit: String(limit), offset: "0" })}
            />
          </label>
          <label>
            Entity type
            <input
              defaultValue={entityType}
              placeholder="e.g. plan, customer"
              onBlur={(e) => setSearchParams({ action, entity_type: e.target.value, limit: String(limit), offset: "0" })}
            />
          </label>
        </div>

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
              </tr>
            </thead>
            <tbody>
              {page?.items.map((entry, i) => (
                <Fragment key={i}>
                  <tr className="clickable" onClick={() => setExpanded(expanded === i ? null : i)}>
                    <td>{new Date(entry.created_at).toLocaleString()}</td>
                    <td>{entry.actor}</td>
                    <td>{entry.action}</td>
                    <td>
                      {entry.entity_type} {entry.entity_id}
                    </td>
                  </tr>
                  {expanded === i && (entry.old_value || entry.new_value) && (
                    <tr>
                      <td colSpan={4}>
                        <pre style={{ overflowX: "auto", fontSize: 12, margin: 0 }}>
                          {JSON.stringify({ old: entry.old_value, new: entry.new_value }, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {page === null && !error && <p>Loading...</p>}
        {page && page.items.length === 0 && <p className="hint">No audit entries match.</p>}
        {page && (
          <Pagination
            total={page.total}
            limit={page.limit}
            offset={page.offset}
            onOffsetChange={(next) =>
              setSearchParams({ action, entity_type: entityType, limit: String(limit), offset: String(next) })
            }
            onLimitChange={(next) => setSearchParams({ action, entity_type: entityType, limit: String(next), offset: "0" })}
          />
        )}
      </div>
    </section>
  );
}
