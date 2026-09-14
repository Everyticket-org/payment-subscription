/**
 * Shared "rows per page" defaults for every admin grid backed by a
 * PageOut[T] response (2026-09-14 follow-up: "All page having GRID -
 * apply paginations - default 10, then options for 25, 50, 100").
 *
 * Every admin list endpoint's `limit` query param already accepts 1-100
 * (see backend/app/api/v1/admin_common.py's DEFAULT_LIMIT/MAX_LIMIT), so
 * these four choices are just the frontend's own menu within that range
 * - no backend change was needed to add this.
 */
export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
export const DEFAULT_PAGE_LIMIT = 10;

/** Reads a `limit` value out of a URLSearchParams-style string (or a
 * plain string state), falling back to DEFAULT_PAGE_LIMIT for anything
 * missing, non-numeric, or not one of PAGE_SIZE_OPTIONS - e.g. a bookmarked
 * or hand-edited URL like `?limit=7` shouldn't silently ask the backend
 * for a page size the picker itself never offers. */
export function parsePageLimit(raw: string | null | undefined): number {
  const parsed = Number(raw);
  return PAGE_SIZE_OPTIONS.includes(parsed as (typeof PAGE_SIZE_OPTIONS)[number]) ? parsed : DEFAULT_PAGE_LIMIT;
}
