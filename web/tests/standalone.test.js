import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

import * as standalone from "@/lib/standalone";

const post = (path, body) => standalone.handle(path, { method: "POST", body });
const get = (path) => standalone.handle(path, { method: "GET" });

async function signedIn() {
  return post("/auth/login", { email: "drg.budi@klinik.id", password: "apa saja" });
}

async function analysedCase() {
  const kase = await post("/cases", {
    patient_name: "Anak A",
    anamnesa: { lokasi: "Gigi depan atas", quality: "Ngilu", alasan_kuat: "Nyeri" },
  });
  const files = new FormData();
  files.append("up", new Blob(["x"]), "up.jpg");
  await post(`/cases/${kase.id}/images`, files);
  await post(`/cases/${kase.id}/run`);
  return kase.id;
}

describe("standalone mode", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ diagnosis_md: "# Diagnosis", recommendation_md: "# Rx" }),
      })
    );
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("leaves unimplemented routes to the network", async () => {
    expect(await get("/health")).toBeUndefined();
    expect(await get("/accounts")).toBeUndefined();
  });

  it("opens a local session and derives a display name from the email", async () => {
    const res = await signedIn();
    expect(res.token).toBeTruthy();
    expect(res.user).toMatchObject({ email: "drg.budi@klinik.id", role: "doctor" });
    expect(res.user.name).toBe("Drg Budi");
    await expect(get("/auth/me")).resolves.toMatchObject({ email: "drg.budi@klinik.id" });
  });

  it("reports 401 before sign-in and after sign-out", async () => {
    await expect(get("/auth/me")).rejects.toMatchObject({ status: 401 });
    await signedIn();
    await post("/auth/logout");
    await expect(get("/auth/me")).rejects.toMatchObject({ status: 401 });
  });

  it("starts with an empty history", async () => {
    await signedIn();
    await expect(get("/cases")).resolves.toEqual([]);
  });

  it("records a new case as a draft and lists it newest first", async () => {
    await signedIn();
    const first = await post("/cases", { patient_name: "A", anamnesa: {} });
    const second = await post("/cases", { patient_name: "B", anamnesa: {} });

    expect(first.status).toBe("draft");
    const list = await get("/cases");
    expect(list.map((c) => c.id)).toEqual([second.id, first.id]);
  });

  it("moves a case to uploaded once photos are attached", async () => {
    await signedIn();
    const kase = await post("/cases", { patient_name: "A", anamnesa: {} });
    const files = new FormData();
    files.append("up", new Blob(["x"]), "up.jpg");
    files.append("panoramic", new Blob(["x"]), "pano.png");

    const updated = await post(`/cases/${kase.id}/images`, files);
    expect(updated.status).toBe("uploaded");
    expect(updated.images.map((i) => i.view_key).sort()).toEqual(["panoramic", "up"]);
  });

  it("does not keep uploaded photos in browser storage", async () => {
    await signedIn();
    const id = await analysedCase();
    const stored = JSON.stringify(await get(`/cases/${id}`));
    // Only the view names are retained — never image bytes or object URLs.
    expect(stored).not.toContain("blob:");
    expect(stored).not.toContain("data:image");
  });

  it("progresses an analysis to done and resolves it to a bundled dataset", async () => {
    vi.useFakeTimers();
    await signedIn();
    const id = await analysedCase();

    const started = await get(`/cases/${id}/status`);
    expect(started.status).toBe("running");
    expect(started.progress).toBeLessThan(100);
    expect(started.stage).toBeTruthy();

    vi.advanceTimersByTime(60_000);
    const finished = await get(`/cases/${id}/status`);
    expect(finished.status).toBe("done");
    expect(finished.progress).toBe(100);
    expect(finished.dataset_id).toBeTruthy();
  });

  it("attaches the bundled advisory once a case is done", async () => {
    vi.useFakeTimers();
    await signedIn();
    const id = await analysedCase();
    vi.advanceTimersByTime(60_000);

    const kase = await get(`/cases/${id}`);
    expect(kase.status).toBe("done");
    expect(kase.diagnosis_md).toContain("# Diagnosis");
    expect(kase.recommendation_md).toContain("# Rx");
  });

  it("reports an unknown case as 404", async () => {
    await signedIn();
    await expect(get("/cases/nope")).rejects.toMatchObject({ status: 404 });
  });

  it("deletes a case", async () => {
    await signedIn();
    const kase = await post("/cases", { patient_name: "A", anamnesa: {} });
    await standalone.handle(`/cases/${kase.id}`, { method: "DELETE" });
    await expect(get("/cases")).resolves.toEqual([]);
  });

  it("reset() clears the session and the history", async () => {
    await signedIn();
    await post("/cases", { patient_name: "A", anamnesa: {} });

    standalone.reset();

    await expect(get("/cases")).resolves.toEqual([]);
    await expect(get("/auth/me")).rejects.toMatchObject({ status: 401 });
  });

  it("survives storage being unavailable", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    // Private browsing must not crash the app — it just cannot persist.
    await expect(signedIn()).resolves.toBeTruthy();
    setItem.mockRestore();
  });
});
