/**
 * Thin fetch wrapper for the ToothFairy backend.
 *
 * Phase 0: base URL + JSON/error handling + a place to attach the JWT. Auth wiring
 * (token storage, 401 → redirect) is fleshed out in Phase 2 (lib/auth.js).
 */

export const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

// --- token storage ---------------------------------------------------------
// The backend also sets an httpOnly cookie, but a SameSite=Lax cookie is NOT sent
// on cross-origin (`:3000` → `:8000`) fetches. So we persist the login token and
// attach it as a Bearer header on every call — the API accepts either (security.py).
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
