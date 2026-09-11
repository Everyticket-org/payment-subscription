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
 * supported, and plenty for a handful of commands) document.execCommand,
 * rather than pulling in a WYSIWYG library - this codebase has stayed
 * dependency-light throughout (no UI kit anywhere), and the exact HTML
 * execCommand produces doesn't matter for the plan-description call site:
 * the server-side sanitizer is the real authority on what's actually
 * stored there.
 *
 * Uncontrolled by design, like every other form field in this codebase's
 * admin forms (defaultValue + FormData on submit, see AdminPlansPage) -
 * a hidden <input name=...> is kept in sync on every edit so the
 * existing "read the whole form via FormData" submit handlers pick this
 * up exactly like a plain <textarea> would, with zero call-site changes
 * needed beyond swapping the tag.
 *
 * Reused for the admin Notification Templates screen's "Body (HTML)"
 * field (2026-09-11 follow-up: "body html should be editor") via the
 * optional `toolbar`/`allowSourceToggle` props below, rather than a
 * second component - templates need a broader toolbar (underline,
 * headings, a link) since there's no sanitizer trimming the result down
 * server-side for them (app.notifications.email.service renders
 * body_html through Jinja2 verbatim), and they carry Jinja2 template
 * syntax ({{ variable }}, {% if %}...{% endif %}) that a WYSIWYG-only
 * editor risks mangling - so `allowSourceToggle` adds a plain-HTML
 * source view an admin can switch to for exact control, always kept in
 * sync with the visual view through the same hidden input.
 */
import { useEffect, useRef, useState } from "react";

export interface RichTextToolbarItem {
  /** A document.execCommand name, or "formatBlock:<tag>" (e.g.
   * "formatBlock:h2") to wrap the current block in that tag. */
  command: string;
  label: string;
  title: string;
  /** True for commands that need a value prompted from the admin first
   * (currently just "createLink" - asks for a URL via window.prompt). */
  promptForValue?: boolean;
}

const DEFAULT_TOOLBAR: RichTextToolbarItem[] = [
  { command: "bold", label: "B", title: "Bold" },
  { command: "italic", label: "I", title: "Italic" },
  { command: "insertUnorderedList", label: "• List", title: "Bullet list" },
  { command: "insertOrderedList", label: "1. List", title: "Numbered list" },
];

export function RichTextEditor({
  name,
  defaultValue,
  placeholder,
  toolbar = DEFAULT_TOOLBAR,
  allowSourceToggle = false,
}: {
  name: string;
  defaultValue?: string | null;
  placeholder?: string;
  /** Override the default 4-command toolbar - see AdminNotificationsPage's
   * EMAIL_BODY_TOOLBAR for the Notification Templates screen's broader
   * one (kept local to that page rather than exported from here, so
   * this file only exports the component itself). */
  toolbar?: RichTextToolbarItem[];
  /** Adds a "HTML source" / "Visual" toggle button so an admin can drop
   * into plain-HTML editing - needed wherever the content can carry
   * template syntax or markup a WYSIWYG toolbar doesn't expose. */
  allowSourceToggle?: boolean;
}) {
  const editorRef = useRef<HTMLDivElement>(null);
  const hiddenInputRef = useRef<HTMLInputElement>(null);
  const [sourceMode, setSourceMode] = useState(false);
  const [sourceValue, setSourceValue] = useState(defaultValue ?? "");

  useEffect(() => {
    if (editorRef.current) {
      editorRef.current.innerHTML = defaultValue ?? "";
    }
    if (hiddenInputRef.current) {
      hiddenInputRef.current.value = defaultValue ?? "";
    }
    setSourceValue(defaultValue ?? "");
    setSourceMode(false);
    // Only re-seed when a different record's value is loaded in, not on
    // every render - otherwise typing would fight the cursor position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultValue]);

  function sync() {
    if (editorRef.current && hiddenInputRef.current) {
      hiddenInputRef.current.value = editorRef.current.innerHTML;
    }
  }

  function runCommand(item: RichTextToolbarItem) {
    editorRef.current?.focus();
    if (item.promptForValue) {
      const url = window.prompt("Link URL (include https://)");
      if (!url) return;
      document.execCommand(item.command, false, url);
    } else if (item.command.startsWith("formatBlock:")) {
      const tag = item.command.slice("formatBlock:".length);
      document.execCommand("formatBlock", false, tag);
    } else {
      document.execCommand(item.command);
    }
    sync();
  }

  function switchToSource() {
    if (editorRef.current) setSourceValue(editorRef.current.innerHTML);
    setSourceMode(true);
  }

  function switchToVisual() {
    if (editorRef.current) editorRef.current.innerHTML = sourceValue;
    if (hiddenInputRef.current) hiddenInputRef.current.value = sourceValue;
    setSourceMode(false);
  }

  return (
    <div className="rte">
      <div className="rte-toolbar">
        {!sourceMode &&
          toolbar.map((btn) => (
            <button
              key={btn.command}
              type="button"
              className="rte-button"
              title={btn.title}
              onMouseDown={(e) => e.preventDefault() /* keep focus/selection in the editor */}
              onClick={() => runCommand(btn)}
            >
              {btn.label}
            </button>
          ))}
        {allowSourceToggle && (
          <button
            type="button"
            className="rte-button rte-button-source"
            onClick={sourceMode ? switchToVisual : switchToSource}
          >
            {sourceMode ? "Back to visual" : "HTML source"}
          </button>
        )}
      </div>
      {sourceMode ? (
        <textarea
          className="rte-source"
          rows={12}
          value={sourceValue}
          onChange={(e) => {
            setSourceValue(e.target.value);
            if (hiddenInputRef.current) hiddenInputRef.current.value = e.target.value;
          }}
        />
      ) : (
        <div
          ref={editorRef}
          className="rte-content"
          contentEditable
          suppressContentEditableWarning
          data-placeholder={placeholder}
          onInput={sync}
          onBlur={sync}
        />
      )}
      <input ref={hiddenInputRef} type="hidden" name={name} />
    </div>
  );
}
