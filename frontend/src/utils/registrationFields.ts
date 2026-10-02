import type { RegistrationFormFieldOut } from "../api/types";

/** True for a "Show only for plans" question (e.g. the Custom plan's
 * expected tickets / ticket price) - asked every time someone subscribes
 * or switches to that plan, unlike general fields (first signup only). */
export function isPlanSpecificField(field: RegistrationFormFieldOut): boolean {
  return (field.plan_codes?.length ?? 0) > 0;
}
