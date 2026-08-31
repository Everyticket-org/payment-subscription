/**
 * App-wide toast notifications ("Keep toaster messages for any updates").
 * Used by every admin mutation (plans, config, invoices, webhooks,
 * customers, registration form, testing tools) and the customer portal's
 * upgrade/downgrade/renew/cancel actions - a lightweight, auto-dismissing
 * confirmation for "this update went through" (or a readable reason why
 * it didn't), layered on top of - not replacing - the inline
 * <ErrorBanner> forms already use for field-level validation errors.
 */
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";

type ToastKind = "success" | "error" | "info";

interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  success: (message: string) => void;
  error: (messageOrError: unknown) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 4500;

/** Extracts a human-readable message from anything a catch block might
 * hand it - an ApiError (structured backend error), a plain Error, or
 * something unexpected - mirroring ErrorBanner's own fallback text so
 * the toast and any inline banner for the same failure never disagree. */
export function toastMessageFor(messageOrError: unknown): string {
  if (typeof messageOrError === "string") return messageOrError;
  if (messageOrError instanceof ApiError) return messageOrError.message;
  if (messageOrError instanceof Error) return messageOrError.message;
  return "Something went wrong. Please try again.";
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, kind, message }]);
      window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const value: ToastContextValue = {
    success: useCallback((message: string) => push("success", message), [push]),
    error: useCallback((messageOrError: unknown) => push("error", toastMessageFor(messageOrError)), [push]),
    info: useCallback((message: string) => push("info", message), [push]),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`}>
            <span className="toast-message">{t.message}</span>
            <button className="toast-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
              &times;
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast() must be used inside <ToastProvider>");
  return ctx;
}
