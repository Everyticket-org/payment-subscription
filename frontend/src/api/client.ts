/**
 * Thin fetch wrapper for the subscription backend.
 *
 * - Base URL comes from VITE_API_BASE_URL (see .env.example) so this
 *   works unchanged against local dev, staging, or prod - never
 *   hardcoded here.
 * - Every backend error is a structured {error_code, message} JSON body
 *   (see backend/app/main.py's AppError handler); ApiError below
 *   preserves both so callers can branch on error_code (e.g. show a
 *   dedicated "verify OTP first" screen for OTP_VERIFICATION_REQUIRED)
 *   instead of just displaying raw text.
 * - Bearer tokens are passed in explicitly per call rather than read
 *   from a global - keeps this module free of React/storage
 *   dependencies so it's easy to test in isolation.
 */
import type { ApiErrorBody } from "./types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

export class ApiError extends Error {
  errorCode: string;
  status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.errorCode = body.error_code;
    this.status = status;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (options.token) {
    headers["Authorization"] = `Bearer ${options.token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    // Network failure (backend down, CORS, offline) - never leak the raw
    // TypeError to the UI, but keep the distinction from a structured
    // API error via a dedicated error_code the UI can check for.
    throw new ApiError(0, {
      error_code: "NETWORK_ERROR",
      message: "Couldn't reach the server. Is the backend running?",
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const body: ApiErrorBody =
      data && typeof data === "object" && "error_code" in data
        ? (data as ApiErrorBody)
        : { error_code: "UNKNOWN_ERROR", message: `Request failed (${response.status})` };
    throw new ApiError(response.status, body);
  }

  return data as T;
}

export const api = {
  get: <T>(path: string, token?: string | null) => request<T>(path, { method: "GET", token }),
  post: <T>(path: string, body?: unknown, token?: string | null) =>
    request<T>(path, { method: "POST", body: body ?? {}, token }),
};
