/**
 * Admin Plans / Plan Features / Plan Transitions (spec sections 14-16, 51).
 * One page: a plans table, an expandable edit panel per plan (fields +
 * features), a "new plan" form, and a transitions allow-list manager.
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
  adminUpdatePlan,
  adminUpdatePlanFeature,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { PlanAdminOut, PlanTransitionOut } from "../../api/types";

export function AdminPlansPage() {
  const { adminToken } = useAuth();
  const [plans, setPlans] = useState<PlanAdminOut[] | null>(null);
  const [transitions, setTransitions] = useState<PlanTransitionOut[] | null>(null);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [showCreate, setShowCreate] = useState(false);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListPlans(adminToken).then(setPlans).catch(setError);
    adminListPlanTransitions(adminToken).then(setTransitions).catch(setError);
  }, [adminToken]);

  useEffect(reload, [reload]);

  const selectedPlan = plans?.find((p) => p.plan_code === selectedCode) ?? null;

  async function handleCreatePlan(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminToken) return;
    const form = new FormData(e.currentTarget);
    try {
      await adminCreatePlan(
        {
          plan_code: String(form.get("plan_code")),
          name: String(form.get("name")),
          description: String(form.get("description") || "") || undefined,
          price: Number(form.get("price")),
          currency: String(form.get("currency") || "INR"),
          billing_interval: (form.get("billing_interval") as "month" | "year") || "month",
          billing_frequency: Number(form.get("billing_frequency") || 1),
        },
        adminToken,
      );
      setShowCreate(false);
      reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <section>
      <div className="page-header-row" style={{ maxWidth: "none" }}>
        <h1>Plans</h1>
        <button className="button button-primary" onClick={() => setShowCreate((v) => !v)}>
          {showCreate ? "Cancel" : "New plan"}
        </button>
      </div>

      <ErrorBanner error={error} />

      {showCreate && (
        <form className="admin-panel" onSubmit={handleCreatePlan} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <h3>New plan</h3>
          <div className="inline-form" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
            <label>
              Plan code
              <input name="plan_code" required placeholder="STARTER" />
            </label>
            <label>
              Name
              <input name="name" required placeholder="Starter" />
            </label>
            <label>
              Price
              <input name="price" type="number" step="0.01" min="0.01" required />
            </label>
            <label>
              Currency
              <input name="currency" defaultValue="INR" />
            </label>
            <label>
              Billing interval
              <select name="billing_interval" defaultValue="month">
                <option value="month">month</option>
                <option value="year">year</option>
              </select>
            </label>
            <label>
              Every N intervals
              <input name="billing_frequency" type="number" min="1" defaultValue={1} />
            </label>
          </div>
          <label>
            Description
            <textarea name="description" rows={2} />
          </label>
          <button className="button button-primary" type="submit">
            Create plan
          </button>
        </form>
      )}

      <div className="admin-panel">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th className="numeric">Price</th>
                <th>Billing</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {plans?.map((plan) => (
                <tr
                  key={plan.plan_code}
                  className="clickable"
                  onClick={() => setSelectedCode(plan.plan_code === selectedCode ? null : plan.plan_code)}
                >
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {plans === null && !error && <p>Loading plans...</p>}
      </div>

      {selectedPlan && <PlanDetailPanel plan={selectedPlan} onChanged={reload} />}

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
                          reload();
                        } catch (err) {
                          setError(err);
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
                reload();
              } catch (err) {
                setError(err);
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
    </section>
  );
}

function PlanDetailPanel({ plan, onChanged }: { plan: PlanAdminOut; onChanged: () => void }) {
  const { adminToken } = useAuth();
  const [error, setError] = useState<unknown>(null);

  async function handleUpdate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!adminToken) return;
    const form = new FormData(e.currentTarget);
    try {
      await adminUpdatePlan(
        plan.plan_code,
        {
          name: String(form.get("name")),
          description: String(form.get("description") || "") || undefined,
          price: Number(form.get("price")),
          billing_interval: (form.get("billing_interval") as "month" | "year") || "month",
          billing_frequency: Number(form.get("billing_frequency") || 1),
          active: form.get("active") === "on",
        },
        adminToken,
      );
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="admin-panel">
      <h2>Edit {plan.name}</h2>
      <ErrorBanner error={error} />
      <form onSubmit={handleUpdate} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="inline-form" style={{ borderTop: "none", paddingTop: 0, marginTop: 0 }}>
          <label>
            Name
            <input name="name" defaultValue={plan.name} required />
          </label>
          <label>
            Price
            <input name="price" type="number" step="0.01" min="0.01" defaultValue={plan.price} required />
          </label>
          <label>
            Billing interval
            <select name="billing_interval" defaultValue={plan.billing_interval}>
              <option value="month">month</option>
              <option value="year">year</option>
            </select>
          </label>
          <label>
            Every N intervals
            <input name="billing_frequency" type="number" min="1" defaultValue={plan.billing_frequency} />
          </label>
          <label>
            <span>Active</span>
            <input name="active" type="checkbox" defaultChecked={plan.active} style={{ width: 18, height: 18 }} />
          </label>
        </div>
        <label>
          Description
          <textarea name="description" rows={2} defaultValue={plan.description ?? ""} />
        </label>
        <button className="button button-primary" type="submit" style={{ width: "fit-content" }}>
          Save plan
        </button>
      </form>

      <h3 style={{ marginTop: 20 }}>Features</h3>
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
                        onChanged();
                      } catch (err) {
                        setError(err);
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
                        onChanged();
                      } catch (err) {
                        setError(err);
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
                        onChanged();
                      } catch (err) {
                        setError(err);
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
            onChanged();
          } catch (err) {
            setError(err);
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
