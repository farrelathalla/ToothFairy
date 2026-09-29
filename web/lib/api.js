import * as standalone from "@/lib/standalone";

/**
 * Thin fetch wrapper for the ToothFairy API gateway.
 *
 * The gateway (Go) is the only backend the browser talks to; it owns identity and case
 * records and forwards the expensive work to the Python ML service internally.
 */

export const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8081";

/**
 * Standalone mode: serve the API from the browser instead of the network.
 *
 * ToothFairy is an installable PWA used on clinic tablets, so it has to stay usable when the
 * gateway is unreachable. With this on, `lib/standalone.js` answers the same routes from
 * local storage and the bundled analysis datasets; requests it does not implement still fall
 * through to the network. Set `NEXT_PUBLIC_STANDALONE=0` to always use the gateway.
 */
const STANDALONE =
  typeof process === "undefined" || process.env.NEXT_PUBLIC_STANDALONE !== "0";

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

// --- token storage ---------------------------------------------------------
// The gateway also sets an httpOnly cookie, but a SameSite=Lax cookie is NOT sent on a
// cross-origin (`:3000` → `:8081`) fetch. So we persist the login token and attach it as a
// Bearer header on every call — the gateway accepts either credential.
const TOKEN_KEY = "tf_token";

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* SSR / no storage */
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * @param {string} path            e.g. "/auth/login"
 * @param {object} [opts]
 * @param {string} [opts.method]
 * @param {any}    [opts.body]     plain object → JSON, or FormData passed through
 * @param {string} [opts.token]    bearer token (until cookie-based auth lands)
 * @param {object} [opts.headers]
 */
export async function apiFetch(path, opts = {}) {
  const { method = "GET", body, token, headers = {} } = opts;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;

  if (STANDALONE && typeof window !== "undefined") {
    let handled;
    try {
      handled = await standalone.handle(path, { method, body });
    } catch (e) {
      // Surface local failures in the same shape as network ones, so callers keep their
      // single `instanceof ApiError` check (auth.jsx treats 401/403 as "not signed in").
      throw new ApiError(e.message, e.status ?? 500, null);
    }
    if (handled !== undefined) return handled;
  }

  const finalHeaders = { ...headers };
  const authToken = token || getToken();
  if (authToken) finalHeaders["Authorization"] = `Bearer ${authToken}`;
  if (body !== undefined && !isForm) finalHeaders["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: finalHeaders,
    credentials: "include",
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const message =
      (data && (data.detail || data.message)) || `Request failed (${res.status})`;
    throw new ApiError(message, res.status, data);
  }
  return data;
}

export const api = {
  get: (path, opts) => apiFetch(path, { ...opts, method: "GET" }),
  post: (path, body, opts) => apiFetch(path, { ...opts, method: "POST", body }),
  patch: (path, body, opts) => apiFetch(path, { ...opts, method: "PATCH", body }),
  del: (path, opts) => apiFetch(path, { ...opts, method: "DELETE" }),
};

/**
 * Absolute URL for a patient photo served by the gateway's `/media` mount.
 *
 * `/media` is authenticated — patient photos are not public — but an `<img>` element cannot
 * send an Authorization header, so the gateway also accepts the session token as a query
 * parameter on that route only. Responses there are `no-store` and the gateway logs paths
 * without query strings, so the token does not linger in caches or access logs.
 */
export function mediaUrl(url) {
  if (!url) return "";
  if (url.startsWith("http")) return url;
  const token = getToken();
  return `${API_BASE}${url}${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}
