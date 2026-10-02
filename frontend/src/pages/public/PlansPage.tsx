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
 *
 * 2026-09 pricing refresh (Starter / Institutional / Custom): cards now
 * also render the plan's features - value-bearing ones as highlight rows
 * (ticket limit, overage, onboarding), the rest as a checklist headed by
 * the plan description ("Everything in Starter, plus:") - and a
 * contact-sales plan gets a "Talk to us" mailto CTA instead of Subscribe.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPublicMessages, listPlans } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { sanitizeHtml } from "../../utils/sanitizeHtml";
import { contactSalesHref, formatBillingInterval, formatPlanPrice, splitPlanFeatures } from "../../utils/planDisplay";
import type { Plan } from "../../api/types";

// Purely cosmetic - cycles the plan badge through 3 gradient tones so a
// row of plan cards doesn't read as a wall of identical accent color.
const BADGE_TONES = ["", "tone-2", "tone-3"];

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M4.5 10.5l3.5 3.5 7.5-8"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PlanPrice({ plan }: { plan: Plan }) {
  if (plan.is_contact_sales) {
    return <p className="plan-price plan-price-contact">Talk to us</p>;
  }
  if (plan.is_trial) {
    return <p className="plan-price">Free for {plan.trial_period_days ?? "?"} days</p>;
  }
  return (
    <p className="plan-price">
      {formatPlanPrice(plan.price, plan.currency)}
      <span className="plan-interval"> / {formatBillingInterval(plan)}</span>
    </p>
  );
}

function PlanCta({ plan, supportEmail }: { plan: Plan; supportEmail: string | null }) {
  if (!plan.is_contact_sales) {
    return (
      <Link to={`/subscribe/${plan.plan_code}`} className="button button-primary">
        Subscribe
      </Link>
    );
  }
  const href = contactSalesHref(supportEmail, plan.name);
  // No support email configured yet (Admin -> Configuration -> General):
  // a dead mailto would be worse than an honest note.
  return href ? (
    <a href={href} className="button button-primary">
      Talk to us
    </a>
  ) : (
    <p className="hint plans-contact-fallback">Contact our sales team to get started with {plan.name}.</p>
  );
}

export function PlansPage() {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [supportEmail, setSupportEmail] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    listPlans()
      .then(setPlans)
      .catch(setError);
    // Only needed for a contact-sales plan's CTA - non-critical, so a
    // failure just leaves that CTA on its no-email fallback.
    getPublicMessages()
      .then((msgs) => setSupportEmail(msgs.support_email ?? null))
      .catch(() => {});
  }, []);

  const hasPaidPlans = plans?.some((p) => !p.is_trial && !p.is_contact_sales) ?? false;
  const contactPlans = plans?.filter((p) => p.is_contact_sales) ?? [];

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
        {plans?.map((plan, i) => {
          const { highlights, included } = splitPlanFeatures(plan.features);
          return (
            <article key={plan.plan_code} className="plan-card">
              <div className="plans-card-top">
                <span className={`plans-card-badge ${BADGE_TONES[i % BADGE_TONES.length]}`}>
                  {plan.name.charAt(0).toUpperCase()}
                </span>
                {plan.is_trial && <span className="plans-trial-tag">Free trial</span>}
              </div>
              <h2>{plan.name}</h2>
              <PlanPrice plan={plan} />

              {highlights.length > 0 && (
                <dl className="plan-highlights">
                  {highlights.map((f) => (
                    <div key={f.feature_key} className="plan-highlight">
                      <dt>{f.feature_label}</dt>
                      <dd>{f.feature_value}</dd>
                    </div>
                  ))}
                </dl>
              )}

              {plan.description && (
                // Description is rich-text HTML (spec section 51: bullet-point
                // editor). The server-side sanitizer (app/plans/sanitize.py)
                // is the real trust boundary; sanitizeHtml() is a second,
                // independent allowlist pass run here since this page renders
                // unescaped markup on an unauthenticated route.
                <div className="plan-description" dangerouslySetInnerHTML={{ __html: sanitizeHtml(plan.description) }} />
              )}

              {included.length > 0 && (
                <ul className="plan-feature-list">
                  {included.map((f) => (
                    <li key={f.feature_key}>
                      <span className="plan-feature-check">
                        <CheckIcon />
                      </span>
                      <span>{f.feature_label}</span>
                    </li>
                  ))}
                </ul>
              )}

              <PlanCta plan={plan} supportEmail={supportEmail} />
            </article>
          );
        })}
      </div>

      {plans && (hasPaidPlans || contactPlans.length > 0) && (
        <p className="plans-footnote plans-footnote-tax">
          * Prices exclusive of GST.
          {contactPlans.length > 0 && (
            <> Contact sales for the {contactPlans.map((p) => p.name).join(" / ")} plan.</>
          )}
        </p>
      )}

      <p className="plans-footnote">
        Already have an account? <Link to="/login">Sign in</Link> to manage your subscription instead.
      </p>
    </section>
  );
}
