import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, apiFetch, ApiError } from "@/lib/api";

function mockFetch(status, body, { json = true } = {}) {
  const text = json ? JSON.stringify(body) : body;
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(text),
  });
}

describe("apiFetch", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch(200, { hello: "world" }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("prefixes the base URL and parses JSON", async () => {
    const data = await api.get("/health");
    expect(data).toEqual({ hello: "world" });
    const [url] = fetch.mock.calls[0];
    expect(url).toMatch(/\/health$/);
  });

  it("sends JSON body with Content-Type and stringifies", async () => {
    await api.post("/auth/login", { email: "a@x.io", password: "p" });
    const [, opts] = fetch.mock.calls[0];
    expect(opts.method).toBe("POST");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(opts.body)).toEqual({ email: "a@x.io", password: "p" });
  });

  it("attaches a bearer token when provided", async () => {
    await apiFetch("/auth/me", { token: "tok123" });
    const [, opts] = fetch.mock.calls[0];
    expect(opts.headers["Authorization"]).toBe("Bearer tok123");
  });

  it("does not set JSON content-type for FormData", async () => {
    const fd = new FormData();
    fd.append("x", "1");
    await api.post("/cases/1/images", fd);
    const [, opts] = fetch.mock.calls[0];
    expect(opts.headers["Content-Type"]).toBeUndefined();
    expect(opts.body).toBe(fd);
  });

  it("throws ApiError with status and detail on non-2xx", async () => {
    vi.stubGlobal("fetch", mockFetch(401, { detail: "Email atau kata sandi salah" }));
    await expect(api.post("/auth/login", {})).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Email atau kata sandi salah",
    });
    expect(new ApiError("x", 500)).toBeInstanceOf(Error);
  });
});
