import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listPlans } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import type { Plan } from "../../api/types";

export function PlansPage() {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    listPlans()
      .then(setPlans)
      .catch(setError);
  }, []);

  return (
    <section>
      <h1>Choose a plan</h1>
      <p className="lede">
        New here? Pick a plan below to subscribe. Already have an account?{" "}
        <Link to="/login">Sign in</Link> to manage your subscription instead.
      </p>

      <ErrorBanner error={error} />

      {plans === null && !error && <p>Loading plans...</p>}

      <div className="plan-grid">
        {plans?.map((plan) => (
          <article key={plan.plan_code} className="plan-card">
            <h2>{plan.name}</h2>
            <p className="plan-price">
              {plan.currency} {plan.price.toFixed(2)}
              <span className="plan-interval">
                {" "}
                / {plan.billing_frequency > 1 ? `${plan.billing_frequency} ` : ""}
                {plan.billing_interval}
                {plan.billing_frequency > 1 ? "s" : ""}
              </span>
            </p>
            {plan.description && <p className="plan-description">{plan.description}</p>}
            <Link to={`/subscribe/${plan.plan_code}`} className="button button-primary">
              Subscribe
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
