"""Server-side sanitization for the plan description rich-text editor
(spec section 51's Plans admin module).

The admin frontend's description field is a contentEditable rich-text
editor (bold/italic/bullet+numbered lists), so what arrives here is raw
HTML from a browser, not plain text - and that same HTML is later
rendered unescaped (`dangerouslySetInnerHTML`) on the *public,
unauthenticated* plan listing page. This is the actual trust boundary for
that HTML: everything downstream (the public listing page, the admin
listing page) treats a stored description as already-safe-to-render, so
this function is the one place that decides what's allowed to survive.

Deliberately allows only a minimal formatting set with ZERO attributes on
any tag - no `href`, `src`, `style`, `class`, or any `on*` event handler
survives, which is what actually closes off the XSS surface (there is no
tag combination in the allowlist that can execute script or load a
remote resource). Links are not in scope here (the ask was bold/italic/
bullet points, not link insertion), so `<a>` is deliberately excluded
too rather than allowing it with a scheme-restricted `href` - one less
thing to get subtly wrong.
"""
import bleach

_ALLOWED_TAGS = ["p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li"]


def sanitize_description(html: str | None) -> str | None:
    """Returns None for None/empty input (so an admin clearing the
    description stores NULL, not an empty string), otherwise the HTML
    reduced to _ALLOWED_TAGS with every attribute stripped."""
    if html is None:
        return None
    cleaned = bleach.clean(html, tags=_ALLOWED_TAGS, attributes={}, strip=True).strip()
    return cleaned or None
