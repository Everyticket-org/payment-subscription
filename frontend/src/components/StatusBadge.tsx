/**
 * Maps every status string used across the admin screens (subscription,
 * payment, provisioning, webhook delivery, customer, notification
 * statuses) to one of four badge colors, so every admin table renders
 * status consistently without each page re-implementing its own
 * good/bad/neutral judgment call.
 */
const SUCCESS_VALUES = new Set(["ACTIVE", "SUCCESS", "SENT"]);
const WARNING_VALUES = new Set(["PENDING", "PENDING_PAYMENT", "IN_PROGRESS", "INITIATED"]);
const DANGER_VALUES = new Set([
  "FAILED",
  "PAYMENT_FAILED",
  "EXPIRED",
  "CANCELLED",
  "SUSPENDED",
  "EXHAUSTED",
]);

export function StatusBadge({ value }: { value: string }) {
  const upper = value.toUpperCase();
  let variant = "badge-neutral";
  if (SUCCESS_VALUES.has(upper)) variant = "badge-success";
  else if (WARNING_VALUES.has(upper)) variant = "badge-warning";
  else if (DANGER_VALUES.has(upper)) variant = "badge-danger";

  return <span className={`badge ${variant}`}>{value.replace(/_/g, " ")}</span>;
}
