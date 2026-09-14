/** Prev/Next pager for the admin PageOut[T] list responses (limit/offset,
 * total count) - every admin list screen uses the same shape.
 *
 * 2026-09-14 follow-up ("All page having GRID - apply paginations -
 * default 10, then options for 25, 50, 100"): every grid backed by one
 * of these PageOut responses now also gets a "Rows per page" selector
 * here, rather than each page hardcoding its own fixed limit. The four
 * choices match what the backend already accepts unchanged - every
 * admin list endpoint's `limit` query param has always taken 1-100
 * (see app/api/v1/admin_common.py's DEFAULT_LIMIT/MAX_LIMIT) - so this
 * is a pure frontend addition, no backend change needed. */
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

export function Pagination({
  total,
  limit,
  offset,
  onOffsetChange,
  onLimitChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onOffsetChange: (nextOffset: number) => void;
  /** Omit to render a plain Prev/Next pager with no page-size control
   * (kept optional so any future non-paginatable list can still reuse
   * this component for its Prev/Next behavior alone, though every
   * current caller passes it). */
  onLimitChange?: (nextLimit: number) => void;
}) {
  const hasMultiplePages = total > limit || offset > 0;
  // Previously this whole component hid itself once everything fit on
  // one page. Now that a "Rows per page" selector can live here too, it
  // still hides when there's nothing to page AND no size selector to
  // show; but with a size selector, that stays visible even on a single
  // short page, since the choice itself doesn't depend on how many
  // pages there currently are.
  if (!hasMultiplePages && !onLimitChange) return null;

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div className="pagination">
      {/* 2026-09-14 follow-up ("Keep records per page dropdown at left
          and navigation on right side"): these two groups are now
          explicit flex children in that order, rather than the size
          selector alone carrying the push-right margin - .pagination-nav
          is what gets margin-left: auto now, so it (and only it) is
          pushed to the far end of the row when both groups are present. */}
      {onLimitChange && (
        <label className="pagination-size">
          <span className="hint">Rows per page</span>
          <select
            value={limit}
            onChange={(e) => onLimitChange(Number(e.target.value))}
          >
            {PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
      )}
      {hasMultiplePages && (
        <div className="pagination-nav">
          <button
            className="button button-secondary"
            disabled={offset === 0}
            onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          >
            Prev
          </button>
          <button
            className="button button-secondary"
            disabled={offset + limit >= total}
            onClick={() => onOffsetChange(offset + limit)}
          >
            Next
          </button>
          <p className="hint">
            {from}-{to} of {total}
          </p>
        </div>
      )}
    </div>
  );
}
