/**
 * Admin Plans / Plan Features / Plan Transitions (spec sections 14-16, 51).
 * Add/Edit plan is a popup (Modal) with a rich-text description editor
 * (bold/italic/bullet+numbered lists); the plans table supports both
 * drag-and-drop and up/down-button reordering, persisted via
 * PUT /admin/plans/reorder and reflected in the same order on the public
 * plan listing page. Feature management and the transitions allow-list
 * stay as their own panels below the table, unchanged in shape.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  adminAddPlanFeature,
  adminCreatePlan,
  adminCreatePlanTransition,
  adminDeletePlanFeature,
  adminDeletePlanTransition,
  adminListPlanTransitions,
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
import type { PlanAdminOut, PlanTransitionOut } from "../../api/types";

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
  const [transitions, setTransitions] = useState<PlanTransitionOut[] | null>(null);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [formState, setFormState] = useState<FormState>(null);
  const [draggedCode, setDraggedCode] = useState<string | null>(null);
  const [reordering, setReordering] = useState(false);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListPlans(adminToken).then(setPlans).catch(setError);
    adminListPlanTransitions(adminToken).then(setTransitions).catch(setError);
  }, [adminToken]);

  useEffect(reload, [reload]);

  const selectedPlan = plans?.find((p) => p.plan_code === selectedCode) ?? null;

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
        <p className="hint">Drag a row (or use the arrows) to reorder - the public plan listing page shows plans in this same order.</p>
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
                    <StatusBadge value={plan.active ? "ACTIVE" : "INACTIVE"} />
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
                      onClick={() => setSelectedCode(plan.plan_code === selectedCode ? null : plan.plan_code)}
                    >
                      {plan.plan_code === selectedCode ? "Hide features" : "Features"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {plans === null && !error && <p>Loading plans...</p>}
      </div>

      {selectedPlan && <PlanFeaturesPanel plan={selectedPlan} onChanged={reload} />}

      <div className="admin-panel">
        <h2>Plan transitions</h2>
        <p className="hint">Explicit upgrade/downgrade allow-list (spec section 16) - absence of a row means the transition is blocked.</p>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>From</th>
                <th>To</th>
                <th>Type</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {transitions?.map((t) => (
                <tr key={t.id}>
                  <td>{t.from_plan_code}</td>
                  <td>{t.to_plan_code}</td>
                  <td>{t.transition_type}</td>
                  <td>
                    <button
                      className="button button-danger"
                      onClick={async () => {
                        if (!adminToken) return;
                        try {
                          await adminDeletePlanTransition(t.id, adminToken);
                          toast.success("Transition removed");
                          reload();
                        } catch (err) {
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

        {plans && plans.length >= 2 && (
          <form
            className="inline-form"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!adminToken) return;
              const form = new FormData(e.currentTarget);
              try {
                await adminCreatePlanTransition(
                  {
                    from_plan_code: String(form.get("from_plan_code")),
                    to_plan_code: String(form.get("to_plan_code")),
                    transition_type: form.get("transition_type") as "UPGRADE" | "DOWNGRADE",
                  },
                  adminToken,
                );
                (e.target as HTMLFormElement).reset();
                toast.success("Transition added");
                reload();
              } catch (err) {
                toast.error(err);
              }
            }}
          >
            <label>
              From
              <select name="from_plan_code" required>
                {plans.map((p) => (
                  <option key={p.plan_code} value={p.plan_code}>
                    {p.plan_code}
                  </option>
                ))}
              </select>
            </label>
            <label>
              To
              <select name="to_plan_code" required>
                {plans.map((p) => (
                  <option key={p.plan_code} value={p.plan_code}>
                    {p.plan_code}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Type
              <select name="transition_type" required>
                <option value="UPGRADE">UPGRADE</option>
                <option value="DOWNGRADE">DOWNGRADE</option>
              </select>
            </label>
            <button className="button button-secondary" type="submit">
              Add transition
            </button>
          </form>
        )}
      </div>

      <PlanFormModal
        state={formState}
        onClose={() => setFormState(null)}
        onSaved={() => {
          setFormState(null);
          reload();
        }}
      />
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
            active: form.get("active") === "on",
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
          {isEdit && (
            <label>
              <span>Active</span>
              <input name="active" type="checkbox" defaultChecked={plan?.active} style={{ width: 18, height: 18 }} />
            </label>
          )}
        </div>
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

function PlanFeaturesPanel({ plan, onChanged }: { plan: PlanAdminOut; onChanged: () => void }) {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [error, setError] = useState<unknown>(null);

  return (
    <div className="admin-panel">
      <h2>{plan.name} - features</h2>
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
    </div>
  );
}
