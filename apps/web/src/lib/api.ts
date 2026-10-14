import {
  getInterfaceLanguage,
  getInterfaceLocale,
  uiKnownText,
  uiText,
} from "./i18n";
import { messageLabels } from "./message-labels";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code: string,
    public requestId?: string,
    public retryAfterSeconds?: number,
  ) {
    super(message);
  }
}

export function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const cookie = document.cookie
    .split(";")
    .find((part) => part.trim().startsWith("cq_csrf="));
  return cookie ? decodeURIComponent(cookie.trim().slice(8)) : "";
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const submittedSession = csrfToken();
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (
    options.method &&
    !["GET", "HEAD", "OPTIONS"].includes(options.method.toUpperCase())
  ) {
    headers.set("X-CSRF-Token", submittedSession);
  }
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  // Cancellation may interrupt the response body after fetch already resolved.
  // An obsolete response must not expire a newer account or become null data.
  options.signal?.throwIfAborted();
  if (!response.ok) {
    const data = (body ?? {}) as {
      error?: { message?: string; error_code?: string; request_id?: string };
      detail?: string | { message?: string; error_code?: string };
      message?: string;
      error_code?: string;
      request_id?: string;
    };
    const detail =
      typeof data.detail === "string" ? data.detail : data.detail?.message;
    const message =
      data.error?.message ||
      data.message ||
      detail ||
      `Request failed (${response.status}). Please try again.`;
    const retryHeader = response.headers.get("Retry-After");
    const retryAfter = retryHeader
      ? /^\d+$/.test(retryHeader)
        ? Number(retryHeader)
        : Math.max(0, Math.ceil((Date.parse(retryHeader) - Date.now()) / 1000))
      : undefined;
    if (
      response.status === 401 &&
      path !== "/me" &&
      typeof window !== "undefined" &&
      csrfToken() === submittedSession &&
      !["INVALID_CREDENTIALS", "MFA_CODE_INVALID"].includes(
        data.error?.error_code || data.error_code || "",
      )
    )
      window.dispatchEvent(new Event("cq:unauthorized"));
    throw new ApiError(
      response.status,
      message,
      data.error?.error_code || data.error_code || "request_failed",
      data.request_id || data.error?.request_id,
      retryAfter !== undefined && Number.isFinite(retryAfter)
        ? retryAfter
        : undefined,
    );
  }
  return body as T;
}

export function post<T>(
  path: string,
  body: unknown = {},
  signal?: AbortSignal,
): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(body), signal });
}

export function number(value: number | undefined | null): string {
  return new Intl.NumberFormat(getInterfaceLocale()).format(value || 0);
}
let displayTimeZone = "UTC";
const dateFormatters = new Map<string, Intl.DateTimeFormat>();
const supportedTimeZones = new Map<string, boolean>();

export function timeZoneSupported(timeZone: string): boolean {
  const cached = supportedTimeZones.get(timeZone);
  if (cached !== undefined) return cached;
  let supported = false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone });
    supported = true;
  } catch {}
  if (supportedTimeZones.size >= 32) supportedTimeZones.clear();
  supportedTimeZones.set(timeZone, supported);
  return supported;
}

export function setDisplayTimeZone(timeZone?: string): void {
  displayTimeZone = timeZone || "UTC";
}

export function getDisplayTimeZone(timeZone = displayTimeZone): string {
  return timeZoneSupported(timeZone) ? timeZone : "UTC";
}

export function date(
  value: string | undefined | null,
  time = false,
  timeZone = displayTimeZone,
): string {
  if (!value) return uiText("Date unavailable");
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  if (dateOnly && parsed.toISOString().slice(0, 10) !== value) return value;
  const zone = dateOnly ? "UTC" : getDisplayTimeZone(timeZone);
  const includeTime = time && !dateOnly;
  const key = `${getInterfaceLocale()}:${zone}:${includeTime}`;
  let formatter = dateFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(getInterfaceLocale(), {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: zone,
      ...(includeTime
        ? {
            hour: "2-digit",
            minute: "2-digit",
            timeZoneName: "short",
          }
        : {}),
    });
    if (dateFormatters.size >= 16) dateFormatters.clear();
    dateFormatters.set(key, formatter);
  }
  return formatter.format(parsed);
}
export function bytes(value: number): string {
  if (value < 1024) return `${number(value)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024,
    i = 0;
  while (amount >= 1024 && i < units.length - 1) {
    amount /= 1024;
    i += 1;
  }
  return `${new Intl.NumberFormat(getInterfaceLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(amount)} ${units[i]}`;
}
export function label(value: string): string {
  return value.replace(/[_-]/g, " ").replace(/^./, (c) => c.toUpperCase());
}
// Application codes only; user names, source text and tags must stay original.
export function uiLabel(value: string): string {
  const priority = /^(low|normal|high|urgent) priority$/.exec(value);
  if (priority && getInterfaceLanguage() !== "en") {
    return `${uiText("Priority")}: ${uiKnownText(label(priority[1]))}`;
  }
  if (
    /^(pdf|csv|json|zip|html|ocr|imap|imaps|msg|mbox|pst|ost|totp|mfa|api)$/i.test(
      value,
    )
  )
    return value.toUpperCase();
  const message = Object.prototype.hasOwnProperty.call(messageLabels, value)
    ? messageLabels[value]
    : label(value);
  return uiKnownText(message);
}
