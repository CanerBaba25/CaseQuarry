export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code: string,
    public requestId?: string,
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
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (
    options.method &&
    !["GET", "HEAD", "OPTIONS"].includes(options.method.toUpperCase())
  ) {
    headers.set("X-CSRF-Token", csrfToken());
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
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
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
  return new Intl.NumberFormat("en-US").format(value || 0);
}
export function date(value: string | undefined | null, time = false): string {
  if (!value) return "Date unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(time
      ? {
          hour: "2-digit",
          minute: "2-digit",
          timeZoneName: "short",
          timeZone: "UTC",
        }
      : { timeZone: "UTC" }),
  }).format(parsed);
}
export function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024,
    i = 0;
  while (amount >= 1024 && i < units.length - 1) {
    amount /= 1024;
    i += 1;
  }
  return `${amount.toFixed(1)} ${units[i]}`;
}
export function label(value: string): string {
  return value.replace(/[_-]/g, " ").replace(/^./, (c) => c.toUpperCase());
}
