/**
 * Visual redesign (2026-09-15 follow-up, second pass - "please change
 * layout for plan listing, registration form page as well"). Same
 * elegant/spacious/responsive treatment already shipped for the
 * customer portal pages, extended to this page. Every fetch, state
 * variable and conditional branch below is unchanged from before this
 * pass - only the markup and classNames changed, scoped under the new
 * .plans-page wrapper (and .plans-page-prefixed descendant selectors)
 * in index.css so the shared .plan-grid/.plan-card/.plan-price classes
 * this page has always used - and which ChangePlanPage.tsx also reuses
 * for its own "pick a new plan" grid - are never redefined, only
 * scoped-down for this page specifically.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listPlans } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { sanitizeHtml } from "../../utils/sanitizeHtml";
import type { Plan } from "../../api/types";

// Purely cosmetic - cycles the plan badge through 3 gradient tones so a
// row of plan cards doesn't read as a wall of identical accent color.
const BADGE_TONES = ["", "tone-2", "tone-3"];

export function PlansPage() {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    listPlans()
      .then(setPlans)
      .catch(setError);
  }, []);

  return (
    <section className="plans-page">
      <div className="portal-page-head">
        <div>
          <div className="portal-eyebrow">Everyticket</div>
          <h1>Choose your plan</h1>
          <p>Simple, transparent pricing - switch or cancel anytime from your account.</p>
        </div>
      </div>

      <ErrorBanner error={error} />

      {plans === null && !error && <p>Loading plans...</p>}

      <div className="plan-grid">
        {plans?.map((plan, i) => (
          <article key={plan.plan_code} className="plan-card">
            <div className="plans-card-top">
              <span className={`plans-card-badge ${BADGE_TONES[i % BADGE_TONES.length]}`}>
                {plan.name.charAt(0).toUpperCase()}
              </span>
              {plan.is_trial && <span className="plans-trial-tag">Free trial</span>}
            </div>
            <h2>{plan.name}</h2>
            <p className="plan-price">
              {plan.is_trial ? (
                `Free for ${plan.trial_period_days ?? "?"} days`
              ) : (
                <>
                  {plan.currency} {plan.price.toFixed(2)}
                  <span className="plan-interval">
                    {" "}
                    / {plan.billing_frequency > 1 ? `${plan.billing_frequency} ` : ""}
                    {plan.billing_interval}
                    {plan.billing_frequency > 1 ? "s" : ""}
                  </span>
                </>
              )}
            </p>
            {plan.description && (
              // Description is rich-text HTML (spec section 51: bullet-point
              // editor). The server-side sanitizer (app/plans/sanitize.py)
              // is the real trust boundary; sanitizeHtml() is a second,
              // independent allowlist pass run here since this page renders
              // unescaped markup on an unauthenticated route.
              <div className="plan-description" dangerouslySetInnerHTML={{ __html: sanitizeHtml(plan.description) }} />
            )}
            <Link to={`/subscribe/${plan.plan_code}`} className="button button-primary">
              Subscribe
            </Link>
          </article>
        ))}
      </div>

      <p className="plans-footnote">
        Already have an account? <Link to="/login">Sign in</Link> to manage your subscription instead.
      </p>
    </section>
  );
}
