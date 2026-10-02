export const CSRF_COOKIE = "career_os_csrf";
export const SIGN_IN_PATH = "/sign-in";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

export function readCookie(name: string): string | null {
  for (const part of document.cookie.split("; ")) {
    const separator = part.indexOf("=");
    if (separator > 0 && part.slice(0, separator) === name) {
      return decodeURIComponent(part.slice(separator + 1));
    }
  }
  return null;
}

let onUnauthorized: () => void = () => {
  window.location.assign(SIGN_IN_PATH);
};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

interface ApiFetchOptions extends Omit<RequestInit, "body" | "credentials"> {
  json?: unknown;
  redirectOnUnauthorized?: boolean;
}

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { code?: string } };
    return body.error?.code ?? "request_failed";
  } catch {
    return "request_failed";
  }
}

export async function apiFetch(path: string, options: ApiFetchOptions = {}): Promise<Response> {
  const { json, redirectOnUnauthorized = true, ...init } = options;
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!SAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) {
      headers.set("X-CSRF-Token", token);
    }
  }
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    method,
    headers,
    credentials: "same-origin",
    body: json === undefined ? null : JSON.stringify(json),
  });
  if (response.status === 401 && redirectOnUnauthorized) {
    onUnauthorized();
  }
  if (!response.ok) {
    throw new ApiRequestError(response.status, await errorCode(response));
  }
  return response;
}
