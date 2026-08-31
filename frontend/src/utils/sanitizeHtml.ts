/**
 * Defense-in-depth allowlist sanitizer for rendering a plan's rich-text
 * description (spec section 51) with dangerouslySetInnerHTML on the
 * public, unauthenticated plan listing page.
 *
 * The real trust boundary is server-side (app/plans/sanitize.py strips
 * everything outside a tiny tag allowlist, with zero attributes, before
 * a description is ever stored) - this is a second, independent pass on
 * the client so a future bug in one layer doesn't automatically become
 * an XSS hole. No dependency (e.g. DOMPurify) needed for an allowlist
 * this small: parse with the browser's own DOMParser, walk the tree,
 * drop anything not on the list along with every attribute, and
 * serialize back to a string.
 */
const ALLOWED_TAGS = new Set(["P", "BR", "STRONG", "B", "EM", "I", "U", "UL", "OL", "LI"]);

export function sanitizeHtml(html: string | null | undefined): string {
  if (!html) return "";

  const parsed = new DOMParser().parseFromString(html, "text/html");
  clean(parsed.body);
  return parsed.body.innerHTML;
}

function clean(node: Node): void {
  // Iterate over a snapshot of childNodes since we mutate (replace) as
  // we go - a live NodeList would skip siblings after a replacement.
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === Node.TEXT_NODE) continue;

    if (child.nodeType !== Node.ELEMENT_NODE) {
      node.removeChild(child);
      continue;
    }

    const el = child as Element;
    if (!ALLOWED_TAGS.has(el.tagName)) {
      // Unwrap rather than delete: keep any text/allowed content this
      // element wrapped, just drop the disallowed wrapper itself
      // (e.g. a stray <div> from a paste) - matches how a formatting-
      // only allowlist should behave for benign structural tags, and
      // for a genuinely dangerous tag (<script>, <svg>, ...) its
      // contents are attacker-controlled markup being re-parsed as
      // text via textContent below, not executed.
      const text = document.createTextNode(el.textContent ?? "");
      node.replaceChild(text, el);
      continue;
    }

    // Strip every attribute - the allowlist tags never need one, and
    // this is what actually closes off event-handler/URL-based XSS.
    for (const attr of Array.from(el.attributes)) {
      el.removeAttribute(attr.name);
    }
    clean(el);
  }
}
