/**
 * Admin Registration Form fields (spec sections 8, 18, 51). Fields are
 * never hard-deleted, only deactivated (a field_key may already be
 * referenced by existing customer registration data) - deactivating
 * also removes it from the public dynamic form renderer immediately.
 *
 * Edit is a popup (Modal), same pattern as the Plans page's Add/Edit
 * form, added per Vishal's follow-up ("Give option to Edit field
 * feature") - previously the only edit actions were the two narrow
 * quick-toggle buttons (Required/Active) below; the modal now covers
 * every other editable attribute (label, placeholder, help text,
 * options, display order, and the new regex validation pair) in one
 * place. field_key and field_type are shown read-only in the modal -
 * both are immutable once a field is created (see backend
 * RegistrationFormFieldUpdate, which never accepts either).
 *
 * validation_pattern/validation_message (same follow-up: "give one more
 * option for validation by Regex and validation message fields to be
 * set") are available on both the create form and the edit modal. The
 * pattern is checked server-side on every /subscribe submission (see
 * backend app.forms.validation) - this UI is just where an admin sets
 * it, plus a live "Test pattern" helper so they can sanity-check a regex
 * before saving it.
 */
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  adminCreateRegistrationFormField,
  adminListRegistrationFormFields,
  adminUpdateRegistrationFormField,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Modal } from "../../components/Modal";
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
  const [editingField, setEditingField] = useState<RegistrationFormFieldAdminOut | null>(null);

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
          validation_pattern: String(form.get("validation_pattern") || "") || undefined,
          validation_message: String(form.get("validation_message") || "") || undefined,
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
          <ValidationFields idPrefix="create" />
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
                <th>Validation</th>
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
                  <td>{f.validation_pattern ? <StatusBadge value="REGEX SET" /> : <span className="muted">None</span>}</td>
                  <td>
                    <StatusBadge value={f.active ? "ACTIVE" : "INACTIVE"} />
                  </td>
                  <td style={{ display: "flex", gap: 8 }}>
                    <button className="button button-secondary" onClick={() => setEditingField(f)}>
                      Edit
                    </button>
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

      <EditFieldModal
        field={editingField}
        onClose={() => setEditingField(null)}
        onSaved={() => {
          setEditingField(null);
          reload();
        }}
      />
    </section>
  );
}

/** Regex pattern + custom message inputs, plus a small live "Test pattern"
 * helper - shared between the create form and the edit modal so both
 * stay in sync as this grows. Uncontrolled (name= only) like the rest of
 * the create form; the edit modal below reads/writes these same names
 * via FormData too. */
function ValidationFields({
  idPrefix,
  defaultPattern,
  defaultMessage,
}: {
  idPrefix: string;
  defaultPattern?: string | null;
  defaultMessage?: string | null;
}) {
  const [pattern, setPattern] = useState(defaultPattern || "");
  const [sample, setSample] = useState("");

  const patternError = useMemo(() => {
    if (!pattern) return null;
    try {
      new RegExp(pattern);
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : "Invalid regular expression";
    }
  }, [pattern]);

  const sampleMatches = useMemo(() => {
    if (!pattern || patternError || !sample) return null;
    try {
      return new RegExp(`^(?:${pattern})$`).test(sample);
    } catch {
      return null;
    }
  }, [pattern, patternError, sample]);

  return (
    <div className="inline-form" style={{ borderTop: "none", paddingTop: 0, marginTop: 0, flexDirection: "column", alignItems: "stretch" }}>
      <label>
        Validation pattern (regex, optional)
        <input
          name="validation_pattern"
          id={`${idPrefix}-validation_pattern`}
          defaultValue={defaultPattern || ""}
          placeholder="^[0-9]{6}$"
          onChange={(e) => setPattern(e.target.value)}
        />
      </label>
      {patternError && <p className="field-error">{patternError}</p>}
      <label>
        Validation message (shown to the customer when the pattern doesn't match)
        <input
          name="validation_message"
          id={`${idPrefix}-validation_message`}
          defaultValue={defaultMessage || ""}
          placeholder="Enter a valid value"
        />
      </label>
      {pattern && !patternError && (
        <label>
          Test pattern against a sample value
          <input
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            placeholder="Type a sample value to test..."
          />
          {sample && (
            <span className={sampleMatches ? "field-hint-ok" : "field-hint-error"}>
              {sampleMatches ? "Matches" : "Does not match"}
            </span>
          )}
        </label>
      )}
    </div>
  );
}

function EditFieldModal({
  field,
  onClose,
  onSaved,
}: {
  field: RegistrationFormFieldAdminOut | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setError(null);
  }, [field]);

  if (!field) return null;

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminToken || !field) return;
    const form = new FormData(e.currentTarget);
    const optionsRaw = String(form.get("options") || "");
    try {
      await adminUpdateRegistrationFormField(
        field.id,
        {
          label: String(form.get("label")),
          required: form.get("required") === "on",
          validation_pattern: String(form.get("validation_pattern") || "") || null,
          validation_message: String(form.get("validation_message") || "") || null,
          placeholder: String(form.get("placeholder") || "") || undefined,
          help_text: String(form.get("help_text") || "") || undefined,
          options:
            (field.field_type === "dropdown" || field.field_type === "radio") && optionsRaw
              ? optionsRaw.split(",").map((o) => o.trim()).filter(Boolean)
              : undefined,
          display_order: Number(form.get("display_order") || field.display_order),
        },
        adminToken,
      );
      toast.success(`${form.get("label")} saved`);
      onSaved();
    } catch (err) {
      setError(err);
      toast.error(err);
    }
  }

  return (
    <Modal open title={`Edit ${field.label}`} onClose={onClose}>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <ErrorBanner error={error} />
        <div className="inline-form" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
          <label>
            Field key
            <input value={field.field_key} disabled title="Field key can't be changed after creation" />
          </label>
          <label>
            Type
            <input value={field.field_type} disabled title="Field type can't be changed after creation" />
          </label>
        </div>
        <label>
          Label
          <input name="label" required defaultValue={field.label} />
        </label>
        <div className="inline-form" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input name="required" type="checkbox" defaultChecked={field.required} style={{ width: 18, height: 18 }} />
            <span>Required</span>
          </label>
          <label>
            Display order
            <input name="display_order" type="number" defaultValue={field.display_order} />
          </label>
        </div>
        {(field.field_type === "dropdown" || field.field_type === "radio") && (
          <label>
            Options (comma-separated)
            <input name="options" defaultValue={(field.options || []).join(", ")} />
          </label>
        )}
        <label>
          Placeholder
          <input name="placeholder" defaultValue={field.placeholder || ""} />
        </label>
        <label>
          Help text
          <input name="help_text" defaultValue={field.help_text || ""} />
        </label>
        <ValidationFields idPrefix={`edit-${field.id}`} defaultPattern={field.validation_pattern} defaultMessage={field.validation_message} />
        <button className="button button-primary" type="submit" style={{ width: "fit-content" }}>
          Save changes
        </button>
      </form>
    </Modal>
  );
}
