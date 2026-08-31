/**
 * Minimal rich-text editor for the plan description field (spec section
 * 51: "an editor where we can write bullet points as well"). Bold /
 * italic / bullet list / numbered list only - deliberately no links,
 * images, colors, or headings, matching exactly what was asked for and
 * what the backend's allowlist sanitizer (app/plans/sanitize.py) keeps
 * anyway (anything else typed in here survives the round trip to the
 * server and back only if it's one of those four things).
 *
 * Built on contentEditable + the (deprecated-but-still-universally-
 * supported, and plenty for four commands) document.execCommand, rather
 * than pulling in a WYSIWYG library - this codebase has stayed
 * dependency-light throughout (no UI kit anywhere), and the exact HTML
 * execCommand produces doesn't matter: the server-side sanitizer is the
 * real authority on what's actually stored.
 *
 * Uncontrolled by design, like every other form field in this codebase's
 * admin forms (defaultValue + FormData on submit, see AdminPlansPage) -
 * a hidden <input name=...> is kept in sync on every edit so the
 * existing "read the whole form via FormData" submit handlers pick this
 * up exactly like a plain <textarea> would, with zero call-site changes
 * needed beyond swapping the tag.
 */
import { useEffect, useRef } from "react";

const TOOLBAR: Array<{ command: string; label: string; title: string }> = [
  { command: "bold", label: "B", title: "Bold" },
  { command: "italic", label: "I", title: "Italic" },
  { command: "insertUnorderedList", label: "• List", title: "Bullet list" },
  { command: "insertOrderedList", label: "1. List", title: "Numbered list" },
];

export function RichTextEditor({
  name,
  defaultValue,
  placeholder,
}: {
  name: string;
  defaultValue?: string | null;
  placeholder?: string;
}) {
  const editorRef = useRef<HTMLDivElement>(null);
  const hiddenInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editorRef.current) {
      editorRef.current.innerHTML = defaultValue ?? "";
    }
    if (hiddenInputRef.current) {
      hiddenInputRef.current.value = defaultValue ?? "";
    }
    // Only re-seed when a different plan's value is loaded in, not on
    // every render - otherwise typing would fight the cursor position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultValue]);

  function sync() {
    if (editorRef.current && hiddenInputRef.current) {
      hiddenInputRef.current.value = editorRef.current.innerHTML;
    }
  }

  function runCommand(command: string) {
    editorRef.current?.focus();
    document.execCommand(command);
    sync();
  }

  return (
    <div className="rte">
      <div className="rte-toolbar">
        {TOOLBAR.map((btn) => (
          <button
            key={btn.command}
            type="button"
            className="rte-button"
            title={btn.title}
            onMouseDown={(e) => e.preventDefault() /* keep focus/selection in the editor */}
            onClick={() => runCommand(btn.command)}
          >
            {btn.label}
          </button>
        ))}
      </div>
      <div
        ref={editorRef}
        className="rte-content"
        contentEditable
        suppressContentEditableWarning
        data-placeholder={placeholder}
        onInput={sync}
        onBlur={sync}
      />
      <input ref={hiddenInputRef} type="hidden" name={name} />
    </div>
  );
}
