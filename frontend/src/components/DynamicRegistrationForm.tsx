/**
 * Dynamic registration-form renderer (spec section 8) - renders one
 * input per active RegistrationFormField the backend returns from
 * GET /public/registration-form, instead of a fixed hardcoded field set.
 * Values are collected into a {field_key: value} map matching exactly
 * what SubscribeRequest.registration_data expects.
 *
 * `file` fields render as a disabled placeholder - there's no file
 * upload/storage service yet (see docs/implementation-status.md), so
 * this deliberately doesn't pretend to support them.
 */
import { useEffect, useState } from "react";
import { getRegistrationForm } from "../api/endpoints";
import type { RegistrationFormFieldOut } from "../api/types";

export function useRegistrationFormFields() {
  const [fields, setFields] = useState<RegistrationFormFieldOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    getRegistrationForm().then(setFields).catch(setError);
  }, []);

  return { fields, error };
}

export function DynamicRegistrationForm({
  fields,
  values,
  onChange,
}: {
  fields: RegistrationFormFieldOut[];
  values: Record<string, string>;
  onChange: (fieldKey: string, value: string) => void;
}) {
  if (fields.length === 0) return null;

  return (
    <>
      {fields.map((field) => (
        <label key={field.field_key}>
          {field.label}
          {field.required ? " *" : ""}
          {renderInput(field, values[field.field_key] ?? "", (value) => onChange(field.field_key, value))}
          {field.help_text && <span className="hint">{field.help_text}</span>}
        </label>
      ))}
    </>
  );
}

function renderInput(field: RegistrationFormFieldOut, value: string, onChange: (value: string) => void) {
  const common = {
    required: field.required,
    placeholder: field.placeholder ?? undefined,
    value,
  };

  switch (field.field_type) {
    case "textarea":
      return <textarea {...common} rows={3} onChange={(e) => onChange(e.target.value)} />;
    case "dropdown":
      return (
        <select {...common} onChange={(e) => onChange(e.target.value)}>
          <option value="">Select...</option>
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      );
    case "radio":
      return (
        <span className="button-row">
          {(field.options ?? []).map((opt) => (
            <label key={opt} style={{ flexDirection: "row", alignItems: "center", gap: 6, fontWeight: 400 }}>
              <input
                type="radio"
                name={field.field_key}
                value={opt}
                checked={value === opt}
                required={field.required}
                onChange={(e) => onChange(e.target.value)}
              />
              {opt}
            </label>
          ))}
        </span>
      );
    case "checkbox":
      return (
        <input
          type="checkbox"
          checked={value === "true"}
          onChange={(e) => onChange(e.target.checked ? "true" : "false")}
          style={{ width: 18, height: 18 }}
        />
      );
    case "file":
      return (
        <input disabled placeholder="File upload isn't supported yet" title="File upload isn't supported yet" />
      );
    case "date":
      return <input type="date" {...common} onChange={(e) => onChange(e.target.value)} />;
    case "number":
      return <input type="number" {...common} onChange={(e) => onChange(e.target.value)} />;
    case "email":
      return <input type="email" {...common} onChange={(e) => onChange(e.target.value)} />;
    case "phone":
      return <input type="tel" {...common} onChange={(e) => onChange(e.target.value)} />;
    case "url":
      return <input type="url" {...common} onChange={(e) => onChange(e.target.value)} />;
    default:
      return <input type="text" {...common} onChange={(e) => onChange(e.target.value)} />;
  }
}
