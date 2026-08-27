import { ApiError } from "../api/client";

/** Renders an ApiError's message with its error_code as a small
 * secondary label - lets a user relay something specific ("I got
 * OTP_VERIFICATION_REQUIRED") without exposing a raw stack trace. */
export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;

  if (error instanceof ApiError) {
    return (
      <div className="banner banner-error" role="alert">
        <strong>{error.message}</strong>
        <span className="banner-code">{error.errorCode}</span>
      </div>
    );
  }

  return (
    <div className="banner banner-error" role="alert">
      <strong>Something went wrong. Please try again.</strong>
    </div>
  );
}
