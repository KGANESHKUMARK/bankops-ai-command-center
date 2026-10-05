/**
 * Minimal typed HTTP client for the BankOps API.
 *
 * - Same-origin `/api` by default (proxied to FastAPI); no provider credentials ever reach the browser.
 * - Short-lived bearer token kept in sessionStorage (cleared when the tab closes). No cookies are used,
 *   so CSRF does not apply; XSS exposure is limited by CSP and by rendering all untrusted content as text.
 * - Consistent error envelope: {"error": {"code", "message", "request_id", "details"}}.
 */
import type { User } from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");
const SESSION_KEY = "bankops.session";

export interface Session {
  token: string;
  expiresAt: string;
  user: User;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, requestId: string | null = null, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

let unauthorizedHandler: (() => void) | null = null;

export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function notifyUnauthorized(): void {
  unauthorizedHandler?.();
}

export function readSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    if (!session.token || Date.parse(session.expiresAt) <= Date.now()) {
      sessionStorage.removeItem(SESSION_KEY);
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export function writeSession(session: Session | null): void {
  if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  else sessionStorage.removeItem(SESSION_KEY);
}

export function getToken(): string | null {
  return readSession()?.token ?? null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | null | undefined>;
}

export function buildQuery(query?: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}${buildQuery(options.query)}`, {
      method: options.method ?? (body !== undefined ? "POST" : "GET"),
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Cannot reach the BankOps API. Check that the backend is running.");
  }
  const requestId = response.headers.get("X-Request-ID");
  const text = await response.text();
  const data = text ? parseJson(text) : null;
  if (!response.ok) {
    const envelope = (data as { error?: { code?: string; message?: string; request_id?: string; details?: unknown } } | null)?.error;
    if (response.status === 401 && token) notifyUnauthorized();
    throw new ApiError(
      response.status,
      envelope?.code ?? "http_error",
      envelope?.message ?? `Request failed with HTTP ${response.status}.`,
      envelope?.request_id ?? requestId,
      envelope?.details,
    );
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error.";
}
