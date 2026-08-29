/** Prev/Next pager for the admin PageOut[T] list responses (limit/offset,
 * total count) - every admin list screen uses the same shape. */
export function Pagination({
  total,
  limit,
  offset,
  onOffsetChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onOffsetChange: (nextOffset: number) => void;
}) {
  if (total <= limit && offset === 0) return null;

  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div className="pagination">
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
  );
}
