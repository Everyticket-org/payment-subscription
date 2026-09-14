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
 *
 * check_duplicate/duplicate_message (Vishal's later follow-up: "Add one
 * more checkbox to validate duplication (it means any record have
 * similar value then it will not allow user to enter same name) &
 * Validation message for that duplication also should be configured")
 * are available the same way, right below the validation pattern
 * fields - a checkbox plus a message input that only appears once it's
 * checked. There's no client-side preview for this one (unlike the regex
 * "Test pattern" helper) since checking for a duplicate means looking at
 * every other customer's submitted data, which only the backend can do.
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
          required: form.get("required") === "yes",
          validation_pattern: String(form.get("validation_pattern") || "") || undefined,
          validation_message: String(form.get("validation_message") || "") || undefined,
          check_duplicate: form.get("check_duplicate") === "reject",
          duplicate_message: String(form.get("duplicate_message") || "") || undefined,
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
        <form className="admin-panel" onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <h3>New field</h3>
          {/* 2026-09-14 follow-up ("make proper design... use radio at
              places required... Orders of fields should be relevant"):
              fields are now grouped into themed fieldsets in a more
              logical order - identity (key/type, both immutable once
              created) first, then everything about how the field is
              displayed, then the validation/rules that govern it last.
              Placeholder is also a new addition here -
              adminCreateRegistrationFormField already accepted it (see
              handleCreate above), this form just never had an input for
              it before, unlike the edit modal below.

              2026-09-14 follow-up #2 ("Required / Optional - only one
              switch is required, same for duplication values"): Required
              is now a single toggle switch (checked = required) instead
              of the Required/Optional radio pair - uncontrolled like the
              rest of this form, since nothing else conditionally depends
              on it. Same treatment for Allow/Reject duplicate values,
              down in ValidationFields. */}
          <fieldset>
            <legend>Field identity</legend>
            <div className="inline-form" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
              <label>
                Field key
                <input name="field_key" required placeholder="tax_id" pattern="^[a-z][a-z0-9_]*$" />
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
            </div>
          </fieldset>

          <fieldset>
            <legend>Display</legend>
            <div className="inline-form" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
              <label>
                Label
                <input name="label" required placeholder="Tax ID" />
              </label>
              <label>
                Placeholder
                <input name="placeholder" placeholder="e.g. 27AAAAA0000A1Z5" />
              </label>
            </div>
            <label style={{ marginTop: 12 }}>
              Options (dropdown/radio only - comma-separated)
              <input name="options" placeholder="Option A, Option B" />
            </label>
            <label style={{ marginTop: 12 }}>
              Help text
              <input name="help_text" />
            </label>
          </fieldset>

          <fieldset>
            <legend>Validation &amp; rules</legend>
            <label className="toggle-switch-row toggle-switch-row-compact">
              <span className="toggle-switch">
                <input type="checkbox" name="required" value="yes" />
                <span className="toggle-switch-track" aria-hidden="true" />
              </span>
              <span>Required</span>
            </label>
            <div style={{ marginTop: 14 }}>
              <ValidationFields idPrefix="create" />
            </div>
          </fieldset>

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
                <th>Duplicate check</th>
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
                  <td>{f.check_duplicate ? <StatusBadge value="ON" /> : <span className="muted">Off</span>}</td>
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
 * helper, plus the duplicate-value checkbox + its own custom message -
 * shared between the create form and the edit modal so both stay in
 * sync as this grows. Uncontrolled (name= only) like the rest of the
 * create form; the edit modal below reads/writes these same names via
 * FormData too. */
function ValidationFields({
  idPrefix,
  defaultPattern,
  defaultMessage,
  defaultCheckDuplicate,
  defaultDuplicateMessage,
}: {
  idPrefix: string;
  defaultPattern?: string | null;
  defaultMessage?: string | null;
  defaultCheckDuplicate?: boolean;
  defaultDuplicateMessage?: string | null;
}) {
  const [checkDuplicate, setCheckDuplicate] = useState(defaultCheckDuplicate ?? false);
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
      <label className="toggle-switch-row toggle-switch-row-compact">
        <span className="toggle-switch">
          <input
            type="checkbox"
            name="check_duplicate"
            value="reject"
            checked={checkDuplicate}
            onChange={(e) => setCheckDuplicate(e.target.checked)}
          />
          <span className="toggle-switch-track" aria-hidden="true" />
        </span>
        <span>
          Reject duplicate values
          <p className="hint" style={{ margin: "2px 0 0" }}>
            Any record with a similar value is blocked.
          </p>
        </span>
      </label>
      {checkDuplicate && (
        <label>
          Duplicate message (shown to the customer when the value is already in use)
          <input
            name="duplicate_message"
            id={`${idPrefix}-duplicate_message`}
            defaultValue={defaultDuplicateMessage || ""}
            placeholder="This value is already registered"
          />
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
          required: form.get("required") === "yes",
          validation_pattern: String(form.get("validation_pattern") || "") || null,
          validation_message: String(form.get("validation_message") || "") || null,
          check_duplicate: form.get("check_duplicate") === "reject",
          duplicate_message: String(form.get("duplicate_message") || "") || null,
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
      {/* 2026-09-14 follow-up ("make proper design... use radio at
          places required... Orders of fields should be relevant"): same
          fieldset grouping and field order as the "New field" form above
          - identity (read-only here, both immutable after creation),
          then Display, then Validation & rules last.

          2026-09-14 follow-up #2 ("Required / Optional - only one switch
          is required, same for duplication values"): Required is now a
          single toggle switch (checked = required), seeded from the
          field's current value via defaultChecked. */}
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <ErrorBanner error={error} />

        <fieldset>
          <legend>Field identity</legend>
          <div className="inline-form" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
            <label>
              Field key
              <input value={field.field_key} disabled title="Field key can't be changed after creation" />
            </label>
            <label>
              Type
              <input value={field.field_type} disabled title="Field type can't be changed after creation" />
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend>Display</legend>
          <div className="inline-form" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
            <label>
              Label
              <input name="label" required defaultValue={field.label} />
            </label>
            <label>
              Placeholder
              <input name="placeholder" defaultValue={field.placeholder || ""} />
            </label>
            <label>
              Display order
              <input name="display_order" type="number" defaultValue={field.display_order} />
            </label>
          </div>
          {(field.field_type === "dropdown" || field.field_type === "radio") && (
            <label style={{ marginTop: 12 }}>
              Options (comma-separated)
              <input name="options" defaultValue={(field.options || []).join(", ")} />
            </label>
          )}
          <label style={{ marginTop: 12 }}>
            Help text
            <input name="help_text" defaultValue={field.help_text || ""} />
          </label>
        </fieldset>

        <fieldset>
          <legend>Validation &amp; rules</legend>
          <label className="toggle-switch-row toggle-switch-row-compact">
            <span className="toggle-switch">
              <input type="checkbox" name="required" value="yes" defaultChecked={field.required} />
              <span className="toggle-switch-track" aria-hidden="true" />
            </span>
            <span>Required</span>
          </label>
          <div style={{ marginTop: 14 }}>
            <ValidationFields
              idPrefix={`edit-${field.id}`}
              defaultPattern={field.validation_pattern}
              defaultMessage={field.validation_message}
              defaultCheckDuplicate={field.check_duplicate}
              defaultDuplicateMessage={field.duplicate_message}
            />
          </div>
        </fieldset>

        <button className="button button-primary" type="submit" style={{ width: "fit-content" }}>
          Save changes
        </button>
      </form>
    </Modal>
  );
}
