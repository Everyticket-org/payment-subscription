/**
 * Admin Registration Form fields (spec sections 8, 18, 51). Fields are
 * never hard-deleted, only deactivated (a field_key may already be
 * referenced by existing customer registration data) - deactivating
 * also removes it from the public dynamic form renderer immediately.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  adminCreateRegistrationFormField,
  adminListRegistrationFormFields,
  adminUpdateRegistrationFormField,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { RegistrationFormFieldAdminOut } from "../../api/types";

const FIELD_TYPES = ["text", "email", "phone", "number", "dropdown", "radio", "checkbox", "textarea", "date", "url", "file"];

export function AdminRegistrationFormPage() {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [fields, setFields] = useState<RegistrationFormFieldAdminOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [showCreate, setShowCreate] = useState(false);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListRegistrationFormFields(adminToken).then(setFields).catch(setError);
  }, [adminToken]);

  useEffect(reload, [reload]);

  async function handleCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminToken) return;
    const form = new FormData(e.currentTarget);
    const fieldType = String(form.get("field_type"));
    const optionsRaw = String(form.get("options") || "");
    try {
      await adminCreateRegistrationFormField(
        {
          field_key: String(form.get("field_key")),
          label: String(form.get("label")),
          field_type: fieldType,
          required: form.get("required") === "on",
          placeholder: String(form.get("placeholder") || "") || undefined,
          help_text: String(form.get("help_text") || "") || undefined,
          options:
            (fieldType === "dropdown" || fieldType === "radio") && optionsRaw
              ? optionsRaw.split(",").map((o) => o.trim()).filter(Boolean)
              : undefined,
        },
        adminToken,
      );
      setShowCreate(false);
      toast.success("Field added");
      reload();
    } catch (err) {
      setError(err);
      toast.error(err);
    }
  }

  async function toggleActive(field: RegistrationFormFieldAdminOut) {
    if (!adminToken) return;
    try {
      await adminUpdateRegistrationFormField(field.id, { active: !field.active }, adminToken);
      toast.success(field.active ? "Field deactivated" : "Field activated");
      reload();
    } catch (err) {
      setError(err);
      toast.error(err);
    }
  }

  async function toggleRequired(field: RegistrationFormFieldAdminOut) {
    if (!adminToken) return;
    try {
      await adminUpdateRegistrationFormField(field.id, { required: !field.required }, adminToken);
      toast.success("Field updated");
      reload();
    } catch (err) {
      setError(err);
      toast.error(err);
    }
  }

  return (
    <section>
      <div className="page-header-row" style={{ maxWidth: "none" }}>
        <h1>Registration form</h1>
        <button className="button button-primary" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Cancel" : "New field"}
        </button>
      </div>
      <p className="lede">
        Fields collected on the public subscribe form (spec section 8) - the frontend renders exactly
        this list, in this order.
      </p>

      <ErrorBanner error={error} />

      {showCreate && (
        <form className="admin-panel" onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <h3>New field</h3>
          <div className="inline-form" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
            <label>
              Field key
              <input name="field_key" required placeholder="tax_id" pattern="^[a-z][a-z0-9_]*$" />
            </label>
            <label>
              Label
              <input name="label" required placeholder="Tax ID" />
            </label>
            <label>
              Type
              <select name="field_type" defaultValue="text">
                {FIELD_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <input name="required" type="checkbox" style={{ width: 18, height: 18 }} />
              <span>Required</span>
            </label>
          </div>
          <label>
            Options (dropdown/radio only - comma-separated)
            <input name="options" placeholder="Option A, Option B" />
          </label>
          <label>
            Help text
            <input name="help_text" />
          </label>
          <button className="button button-primary" type="submit" style={{ width: "fit-content" }}>
            Add field
          </button>
        </form>
      )}

      <div className="admin-panel">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Key</th>
                <th>Label</th>
                <th>Type</th>
                <th>Required</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {fields?.map((f) => (
                <tr key={f.id}>
                  <td>{f.display_order}</td>
                  <td>{f.field_key}</td>
                  <td>{f.label}</td>
                  <td>{f.field_type}</td>
                  <td>
                    <button className="button button-secondary" onClick={() => toggleRequired(f)}>
                      {f.required ? "Yes" : "No"}
                    </button>
                  </td>
                  <td>
                    <StatusBadge value={f.active ? "ACTIVE" : "INACTIVE"} />
                  </td>
                  <td>
                    <button className="button button-secondary" onClick={() => toggleActive(f)}>
                      {f.active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {fields === null && !error && <p>Loading...</p>}
      </div>
    </section>
  );
}
