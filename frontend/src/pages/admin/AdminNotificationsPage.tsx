/** Admin Notification Templates + Email Logs (spec sections 49-50, 51). */
import { useCallback, useEffect, useState } from "react";
import { adminListNotificationLogs, adminListNotificationTemplates, adminUpdateNotificationTemplate } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { NotificationLogOut, NotificationTemplateOut } from "../../api/types";

export function AdminNotificationsPage() {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [templates, setTemplates] = useState<NotificationTemplateOut[] | null>(null);
  const [logs, setLogs] = useState<NotificationLogOut[] | null>(null);
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListNotificationTemplates(adminToken).then(setTemplates).catch(setError);
    adminListNotificationLogs({ limit: 25, offset: 0 }, adminToken).then((page) => setLogs(page.items)).catch(setError);
  }, [adminToken]);

  useEffect(reload, [reload]);

  const editingTemplate = templates?.find((t) => t.template_code === editingCode) ?? null;

  return (
    <section>
      <h1>Notifications</h1>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <h2>Templates</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Subject</th>
                <th>Active</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {templates?.map((t) => (
                <tr key={t.template_code}>
                  <td>{t.template_code}</td>
                  <td>{t.subject}</td>
                  <td>
                    <StatusBadge value={t.active ? "ACTIVE" : "INACTIVE"} />
                  </td>
                  <td>
                    <button
                      className="button button-secondary"
                      onClick={() => setEditingCode(editingCode === t.template_code ? null : t.template_code)}
                    >
                      {editingCode === t.template_code ? "Close" : "Edit"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {editingTemplate && (
          <form
            className="inline-form"
            style={{ flexDirection: "column", alignItems: "stretch" }}
            onSubmit={async (e) => {
              e.preventDefault();
              if (!adminToken) return;
              const form = new FormData(e.currentTarget);
              try {
                await adminUpdateNotificationTemplate(
                  editingTemplate.template_code,
                  {
                    subject: String(form.get("subject")),
                    body_html: String(form.get("body_html")),
                    active: form.get("active") === "on",
                  },
                  adminToken,
                );
                setEditingCode(null);
                toast.success("Template saved");
                reload();
              } catch (err) {
                setError(err);
                toast.error(err);
              }
            }}
          >
            <label>
              Subject
              <input name="subject" defaultValue={editingTemplate.subject} required />
            </label>
            <label>
              Body (HTML)
              <textarea name="body_html" rows={6} defaultValue={editingTemplate.body_html} required />
            </label>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <input name="active" type="checkbox" defaultChecked={editingTemplate.active} style={{ width: 18, height: 18 }} />
              <span>Active</span>
            </label>
            <button className="button button-primary" type="submit" style={{ width: "fit-content" }}>
              Save template
            </button>
          </form>
        )}
      </div>

      <div className="admin-panel">
        <h2>Recent sends</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Template</th>
                <th>Recipient</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {logs?.map((log, i) => (
                <tr key={i}>
                  <td>{new Date(log.created_at).toLocaleString()}</td>
                  <td>{log.template_code}</td>
                  <td>{log.recipient}</td>
                  <td>
                    <StatusBadge value={log.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {logs === null && !error && <p>Loading...</p>}
        {logs && logs.length === 0 && <p className="hint">No sends yet.</p>}
      </div>
    </section>
  );
}
