/**
 * Shared display helpers for admin screens that show a customer as an
 * avatar + initials (Customers list, Customer detail) or a colored plan
 * pill (Customers list, Customer detail, Dashboard's plan-mix breakdown).
 * Extracted 2026-09-15 (Customer detail page redesign) out of
 * AdminCustomersPage.tsx, which introduced them first - kept here so both
 * pages stay visually identical (same customer always gets the same
 * avatar color, same plan always gets the same pill color) instead of
 * drifting if each page grew its own copy.
 */

// Small cyclical palette convention (also used by the Dashboard's
// plan-mix breakdown, AdminDashboardPage.tsx): colors assigned by
// position in the real plan list, not hardcoded per plan name, so a
// newly added plan gets a sensible color automatically.
export const PLAN_COLORS = ["#d50355", "#7c3aed", "#0891b2", "#ca8a04", "#16a34a", "#64748b"];

// A separate, hash-based palette for customer avatars (stable per
// customer_id across reloads/pagination, not tied to plan).
export const AVATAR_COLORS = ["#d50355", "#7c3aed", "#0891b2", "#ca8a04", "#16a34a", "#64748b", "#dc2626", "#0d9488"];

export function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  }
  return hash;
}

export function avatarColorFor(customerId: string): string {
  return AVATAR_COLORS[hashString(customerId) % AVATAR_COLORS.length];
}

/** Up to two initials from the email's local part (there's no "name"
 * field on a Customer - spec section 7 treats email/mobile as identity
 * attributes, not a display name) - "priya.sharma@x" -> "PS", "admin@x"
 * -> "AD". */
export function initialsFor(email: string): string {
  const local = email.split("@")[0] ?? email;
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0]![0]! + parts[1]![0]!).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase() || "?";
}
