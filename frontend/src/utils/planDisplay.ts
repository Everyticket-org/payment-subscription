/**
 * Presentation helpers for plan cards (2026-09 pricing refresh -
 * Starter / Institutional / Custom). Pure functions, no React.
 */
import type { Plan, PlanFeature } from "../api/types";

/**
 * "₹6,999" / "₹14,999.50" - Indian digit grouping for INR, the currency's
 * own symbol for anything else. Whole amounts drop the ".00" so the card
 * reads like the pricing sheet.
 */
export function formatPlanPrice(amount: number, currency: string): string {
  const locale = currency === "INR" ? "en-IN" : undefined;
  const fractionDigits = Number.isInteger(amount) ? 0 : 2;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(amount);
  } catch {
    // Unknown/invalid ISO code in admin data - never break the page over it.
    return `${currency} ${amount.toFixed(fractionDigits)}`;
  }
}

/** "₹999.00" - receipt-style, always two decimals (payment summary and
 * result pages), unlike formatPlanPrice's card-style "₹999". */
export function formatAmount(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : undefined, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

/** "month", "3 months", "year" - the part after "/" in a price. */
export function formatBillingInterval(plan: Pick<Plan, "billing_frequency" | "billing_interval">): string {
  return plan.billing_frequency > 1
    ? `${plan.billing_frequency} ${plan.billing_interval}s`
    : plan.billing_interval;
}

/** Short one-line price for compact lists (subscribe side panel). */
export function planPriceSummary(plan: Plan): string {
  if (plan.is_contact_sales) return "Talk to us";
  if (plan.is_trial) return `Free for ${plan.trial_period_days ?? "?"} days`;
  return `${formatPlanPrice(plan.price, plan.currency)} / ${formatBillingInterval(plan)}`;
}

/** A plan a customer can subscribe to / switch to on their own. */
export function isSelfServePlan(plan: Plan): boolean {
  return !plan.is_contact_sales;
}

/**
 * Feature convention (see backend app/plans/catalog.py): a feature with a
 * value is a highlight row ("Monthly ticket limit ... 4,000 tickets"), one
 * without is a checklist item ("Event Management").
 */
export function splitPlanFeatures(features: PlanFeature[] | undefined): {
  highlights: PlanFeature[];
  included: PlanFeature[];
} {
  const sorted = [...(features ?? [])].sort((a, b) => a.display_order - b.display_order);
  return {
    highlights: sorted.filter((f) => f.feature_value && f.feature_value.trim() !== ""),
    included: sorted.filter((f) => !f.feature_value || f.feature_value.trim() === ""),
  };
}

// Deliberately strict: the address is interpolated into an href, so
// anything outside a plain local@domain shape is treated as "not set"
// (the backend already validates it as an email on save).
const SIMPLE_EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

/** mailto link for a contact-sales plan's "Talk to us" CTA, or null when
 * no usable support email is configured. */
export function contactSalesHref(supportEmail: string | null | undefined, planName: string): string | null {
  if (!supportEmail || !SIMPLE_EMAIL.test(supportEmail)) return null;
  const subject = encodeURIComponent(`Everyticket ${planName} plan enquiry`);
  return `mailto:${supportEmail}?subject=${subject}`;
}
