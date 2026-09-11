/** Admin Notification Templates + Email Logs (spec sections 49-50, 51).
 *
 * 2026-09-11 follow-up ("notifications email template should 1. Open in
 * popup for edit 2. body html should be editor"): Edit now opens as a
 * Modal popup (same pattern as the Plans Add/Edit form) instead of an
 * inline form expanding below the table, and the Body (HTML) field is
 * now the same RichTextEditor component the plan description field
 * uses - given a broader toolbar (EMAIL_BODY_TOOLBAR: bold/italic/
 * underline/headings/lists/link) since there's no server-side sanitizer
 * trimming a template's body_html the way there is for a plan
 * description, plus a "HTML source" toggle so the Jinja2 template
 * syntax these bodies carry ({{ code }}, {% if %}...{% endif %}) can
 * always be edited exactly, safe from anything the visual toolbar
 * doesn't expose. */
import { useCallback, useEffect, useState } from "react";
import { adminListNotificationLogs, adminListNotificationTemplates, adminUpdateNotificationTemplate } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Modal } from "../../components/Modal";
import { RichTextEditor, type RichTextToolbarItem } from "../../components/RichTextEditor";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { NotificationLogOut, NotificationTemplateOut } from "../../api/types";

/** Broader toolbar than the plan-description editor's default - headings
 * and inline styling show up in the seeded default templates (e.g. the
 * OTP email's large, bold, letter-spaced code), and a link is a normal
 * thing to want in an email body. Kept local to this page (rather than
 * exported from RichTextEditor.tsx) so that shared component file only
 * exports the component itself. */
const EMAIL_BODY_TOOLBAR: RichTextToolbarItem[] = [
  { command: "bold", label: "B", title: "Bold" },
  { command: "italic", label: "I", title: "Italic" },
  { command: "underline", label: "U", title: "Underline" },
  { command: "formatBlock:h2", label: "H2", title: "Heading" },
  { command: "formatBlock:h3", label: "H3", title: "Subheading" },
  { command: "formatBlock:p", label: "¶", title: "Paragraph" },
  { command: "insertUnorderedList", label: "• List", title: "Bullet list" },
  { command: "insertOrderedList", label: "1. List", title: "Numbered list" },
  { command: "createLink", label: "Link", title: "Insert link", promptForValue: true },
  { command: "removeFormat", label: "Clear", title: "Clear formatting" },
];

export function AdminNotificationsPage() {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [templates, setTemplates] = useState<NotificationTemplateOut[] | null>(null);
  const [logs, setLogs] = useState<NotificationLogOut[] | null>(null);
  const [editingCode, setEditingCode] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
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
                    <button className="button button-secondary" onClick={() => setEditingCode(t.template_code)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {templates === null && !error && <p>Loading...</p>}

        <Modal
          open={editingTemplate !== null}
          title={editingTemplate ? `Edit template — ${editingTemplate.template_code}` : "Edit template"}
          onClose={() => setEditingCode(null)}
          wide
        >
          {editingTemplate && (
            <form
              className="inline-form"
              style={{ flexDirection: "column", alignItems: "stretch" }}
              onSubmit={async (e) => {
                e.preventDefault();
                if (!adminToken) return;
                const form = new FormData(e.currentTarget);
                setSaving(true);
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
                } finally {
                  setSaving(false);
                }
              }}
            >
              <label>
                Subject
                <input name="subject" defaultValue={editingTemplate.subject} required />
              </label>
              <label>
                Body (HTML)
                <RichTextEditor
                  key={editingTemplate.template_code}
                  name="body_html"
                  defaultValue={editingTemplate.body_html}
                  toolbar={EMAIL_BODY_TOOLBAR}
                  allowSourceToggle
                  placeholder="Email body HTML..."
                />
              </label>
              <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <input name="active" type="checkbox" defaultChecked={editingTemplate.active} style={{ width: 18, height: 18 }} />
                <span>Active</span>
              </label>
              <button className="button button-primary" type="submit" disabled={saving} style={{ width: "fit-content" }}>
                {saving ? "Saving..." : "Save template"}
              </button>
            </form>
          )}
        </Modal>
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
