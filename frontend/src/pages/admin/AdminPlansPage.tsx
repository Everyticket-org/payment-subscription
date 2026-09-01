/**
 * Admin Plans / Plan Features (spec sections 14-15, 51).
 * Add/Edit plan is a popup (Modal) with a rich-text description editor
 * (bold/italic/bullet+numbered lists); the plans table supports both
 * drag-and-drop and up/down-button reordering, persisted via
 * PUT /admin/plans/reorder and reflected in the same order on the public
 * plan listing page. Active/Inactive is toggled directly from the grid
 * (a click on the status badge, same pattern as the registration-form
 * page's toggleActive) rather than inside the edit form.
 *
 * Feature management is now its own popup (Modal), opened via the
 * "Features" button per row, instead of an inline panel below the table -
 * per Vishal's admin-panel request (2026-09).
 *
 * The Plan Transitions allow-list UI has been removed per the same
 * request ("Plan transitions are not required for now as we are giving
 * dropdown to user for change plan") - the backend PlanTransition
 * model/admin endpoints still exist untouched, they're just not surfaced
 * here any more. See app/subscriptions/service.py's
 * assert_transition_allowed() for the price-based logic that replaced the
 * allow-list requirement.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  adminAddPlanFeature,
  adminCreatePlan,
  adminDeletePlanFeature,
  adminListPlans,
  adminReorderPlans,
  adminUpdatePlan,
  adminUpdatePlanFeature,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Modal } from "../../components/Modal";
import { RichTextEditor } from "../../components/RichTextEditor";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { PlanAdminOut } from "../../api/types";

type FormState = { mode: "create" } | { mode: "edit"; plan: PlanAdminOut } | null;

function movePlanCode(codes: string[], fromIndex: number, toIndex: number): string[] {
  const next = [...codes];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}

export function AdminPlansPage() {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [plans, setPlans] = useState<PlanAdminOut[] | null>(null);
  const [featuresCode, setFeaturesCode] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [formState, setFormState] = useState<FormState>(null);
  const [draggedCode, setDraggedCode] = useState<string | null>(null);
  const [reordering, setReordering] = useState(false);
  const [togglingCode, setTogglingCode] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListPlans(adminToken).then(setPlans).catch(setError);
  }, [adminToken]);

  useEffect(reload, [reload]);

  const featuresPlan = plans?.find((p) => p.plan_code === featuresCode) ?? null;

  async function persistOrder(orderedCodes: string[]) {
    if (!adminToken) return;
    setReordering(true);
    try {
      const updated = await adminReorderPlans(orderedCodes, adminToken);
      setPlans(updated);
      toast.success("Plan order updated");
    } catch (err) {
      toast.error(err);
      reload(); // roll back any optimistic UI to the server's real order
    } finally {
      setReordering(false);
    }
  }

  function handleDrop(targetCode: string) {
    if (!plans || !draggedCode || draggedCode === targetCode) {
      setDraggedCode(null);
      return;
    }
    const codes = plans.map((p) => p.plan_code);
    const from = codes.indexOf(draggedCode);
    const to = codes.indexOf(targetCode);
    setDraggedCode(null);
    if (from === -1 || to === -1) return;
    persistOrder(movePlanCode(codes, from, to));
  }

  function handleNudge(code: string, direction: -1 | 1) {
    if (!plans) return;
    const codes = plans.map((p) => p.plan_code);
    const from = codes.indexOf(code);
    const to = from + direction;
    if (to < 0 || to >= codes.length) return;
    persistOrder(movePlanCode(codes, from, to));
  }

  async function toggleActive(plan: PlanAdminOut) {
    if (!adminToken) return;
    setTogglingCode(plan.plan_code);
    try {
      await adminUpdatePlan(plan.plan_code, { active: !plan.active }, adminToken);
      toast.success(plan.active ? `${plan.name} deactivated` : `${plan.name} activated`);
      reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setTogglingCode(null);
    }
  }

  return (
    <section>
      <div className="page-header-row" style={{ maxWidth: "none" }}>
        <h1>Plans</h1>
        <button className="button button-primary" onClick={() => setFormState({ mode: "create" })}>
          New plan
        </button>
      </div>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <p className="hint">Drag a row (or use the arrows) to reorder - the public plan listing page shows plans in this same order. Click the status badge to activate/deactivate a plan.</p>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th></th>
                <th>Code</th>
                <th>Name</th>
                <th className="numeric">Price</th>
                <th>Billing</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {plans?.map((plan, index) => (
                <tr
                  key={plan.plan_code}
                  className={"reorder-row" + (draggedCode === plan.plan_code ? " dragging" : "")}
                  draggable
                  onDragStart={() => setDraggedCode(plan.plan_code)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => handleDrop(plan.plan_code)}
                  onDragEnd={() => setDraggedCode(null)}
                >
                  <td>
                    <span className="reorder-handle" title="Drag to reorder">
                      &#x2630;
                    </span>
                  </td>
                  <td>{plan.plan_code}</td>
                  <td>{plan.name}</td>
                  <td className="numeric">
                    {plan.currency} {plan.price.toFixed(2)}
                  </td>
                  <td>
                    every {plan.billing_frequency} {plan.billing_interval}
                    {plan.billing_frequency > 1 ? "s" : ""}
                  </td>
                  <td>
                    <button
                      className="button button-secondary"
                      style={{ padding: 0, border: "none", background: "none" }}
                      disabled={togglingCode === plan.plan_code}
                      title={plan.active ? "Click to deactivate" : "Click to activate"}
                      onClick={() => toggleActive(plan)}
                    >
                      <StatusBadge value={plan.active ? "ACTIVE" : "INACTIVE"} />
                    </button>
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <div className="reorder-buttons">
                      <button
                        disabled={index === 0 || reordering}
                        title="Move up"
                        onClick={() => handleNudge(plan.plan_code, -1)}
                      >
                        &#x2191;
                      </button>
                      <button
                        disabled={!plans || index === plans.length - 1 || reordering}
                        title="Move down"
                        onClick={() => handleNudge(plan.plan_code, 1)}
                      >
                        &#x2193;
                      </button>
                    </div>
                    <button
                      className="button button-secondary"
                      style={{ marginLeft: 8 }}
                      onClick={() => setFormState({ mode: "edit", plan })}
                    >
                      Edit
                    </button>
                    <button
                      className="button button-secondary"
                      style={{ marginLeft: 8 }}
                      onClick={() => setFeaturesCode(plan.plan_code)}
                    >
                      Features
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {plans === null && !error && <p>Loading plans...</p>}
      </div>

      <PlanFormModal
        state={formState}
        onClose={() => setFormState(null)}
        onSaved={() => {
          setFormState(null);
          reload();
        }}
      />

      <PlanFeaturesModal plan={featuresPlan} onClose={() => setFeaturesCode(null)} onChanged={reload} />
    </section>
  );
}

function PlanFormModal({
  state,
  onClose,
  onSaved,
}: {
  state: FormState;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [error, setError] = useState<unknown>(null);
  // The rich text editor is uncontrolled (see RichTextEditor's own
  // docstring) and re-seeded from `defaultValue` only when its key
  // changes, so switching between "create" and a specific plan's "edit"
  // needs a fresh key per target rather than relying on remount timing.
  const editorKey = state?.mode === "edit" ? state.plan.plan_code : "create";

  useEffect(() => {
    setError(null);
  }, [state]);

  if (!state) return null;
  const isEdit = state.mode === "edit";
  const plan = isEdit ? state.plan : null;

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminToken) return;
    const form = new FormData(e.currentTarget);
    const description = String(form.get("description") || "") || undefined;

    try {
      if (isEdit && plan) {
        await adminUpdatePlan(
          plan.plan_code,
          {
            name: String(form.get("name")),
            description,
            price: Number(form.get("price")),
            billing_interval: (form.get("billing_interval") as "month" | "year") || "month",
            billing_frequency: Number(form.get("billing_frequency") || 1),
          },
          adminToken,
        );
        toast.success(`${form.get("name")} saved`);
      } else {
        await adminCreatePlan(
          {
            plan_code: String(form.get("plan_code")),
            name: String(form.get("name")),
            description,
            price: Number(form.get("price")),
            currency: String(form.get("currency") || "INR"),
            billing_interval: (form.get("billing_interval") as "month" | "year") || "month",
            billing_frequency: Number(form.get("billing_frequency") || 1),
          },
          adminToken,
        );
        toast.success(`${form.get("name")} created`);
      }
      onSaved();
    } catch (err) {
      setError(err);
      toast.error(err);
    }
  }

  return (
    <Modal open title={isEdit ? `Edit ${plan!.name}` : "New plan"} onClose={onClose} wide>
      <ErrorBanner error={error} />
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="inline-form" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
          {!isEdit && (
            <label>
              Plan code
              <input name="plan_code" required placeholder="STARTER" />
            </label>
          )}
          <label>
            Name
            <input name="name" required placeholder="Starter" defaultValue={plan?.name} />
          </label>
          <label>
            Price
            <input name="price" type="number" step="0.01" min="0.01" required defaultValue={plan?.price} />
          </label>
          {!isEdit && (
            <label>
              Currency
              <input name="currency" defaultValue="INR" />
            </label>
          )}
          <label>
            Billing interval
            <select name="billing_interval" defaultValue={plan?.billing_interval ?? "month"}>
              <option value="month">month</option>
              <option value="year">year</option>
            </select>
          </label>
          <label>
            Every N intervals
            <input name="billing_frequency" type="number" min="1" defaultValue={plan?.billing_frequency ?? 1} />
          </label>
        </div>
        {isEdit && (
          <p className="hint">
            Active/Inactive is set from the plans grid now - close this and click the status badge on {plan!.name}'s row.
          </p>
        )}
        <label>
          Description
          <RichTextEditor key={editorKey} name="description" defaultValue={plan?.description} placeholder="What makes this plan worth it? Use bullet points to list what's included." />
        </label>
        <button className="button button-primary" type="submit" style={{ width: "fit-content" }}>
          {isEdit ? "Save plan" : "Create plan"}
        </button>
      </form>
    </Modal>
  );
}

function PlanFeaturesModal({
  plan,
  onClose,
  onChanged,
}: {
  plan: PlanAdminOut | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setError(null);
  }, [plan]);

  if (!plan) return null;

  return (
    <Modal open title={`${plan.name} - features`} onClose={onClose} wide>
      <ErrorBanner error={error} />
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Label</th>
              <th>Value</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {plan.features.map((feature) => (
              <tr key={feature.id}>
                <td>
                  <input
                    defaultValue={feature.feature_label}
                    onBlur={async (e) => {
                      if (!adminToken || e.target.value === feature.feature_label) return;
                      try {
                        await adminUpdatePlanFeature(plan.plan_code, feature.id, { feature_label: e.target.value }, adminToken);
                        toast.success("Feature updated");
                        onChanged();
                      } catch (err) {
                        setError(err);
                        toast.error(err);
                      }
                    }}
                  />
                </td>
                <td>
                  <input
                    defaultValue={feature.feature_value ?? ""}
                    onBlur={async (e) => {
                      if (!adminToken || e.target.value === (feature.feature_value ?? "")) return;
                      try {
                        await adminUpdatePlanFeature(plan.plan_code, feature.id, { feature_value: e.target.value }, adminToken);
                        toast.success("Feature updated");
                        onChanged();
                      } catch (err) {
                        setError(err);
                        toast.error(err);
                      }
                    }}
                  />
                </td>
                <td>
                  <button
                    className="button button-danger"
                    onClick={async () => {
                      if (!adminToken) return;
                      try {
                        await adminDeletePlanFeature(plan.plan_code, feature.id, adminToken);
                        toast.success("Feature removed");
                        onChanged();
                      } catch (err) {
                        setError(err);
                        toast.error(err);
                      }
                    }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form
        className="inline-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!adminToken) return;
          const form = new FormData(e.currentTarget);
          try {
            await adminAddPlanFeature(
              plan.plan_code,
              {
                feature_key: String(form.get("feature_key")),
                feature_label: String(form.get("feature_label")),
                feature_value: String(form.get("feature_value") || "") || undefined,
              },
              adminToken,
            );
            (e.target as HTMLFormElement).reset();
            toast.success("Feature added");
            onChanged();
          } catch (err) {
            setError(err);
            toast.error(err);
          }
        }}
      >
        <label>
          Key
          <input name="feature_key" required placeholder="storage_gb" />
        </label>
        <label>
          Label
          <input name="feature_label" required placeholder="Storage" />
        </label>
        <label>
          Value
          <input name="feature_value" placeholder="50 GB" />
        </label>
        <button className="button button-secondary" type="submit">
          Add feature
        </button>
      </form>
    </Modal>
  );
}
