import { test, expect } from "@playwright/test";

import { loginAsDoctor, resetLocalData } from "./helpers";

/**
 * The offline path end to end: sign in, create a case, upload photos, watch the analysis
 * progress, and read the results — with no gateway and no ML service running.
 *
 * Everything here goes through the same screens and the same `lib/api.js` calls the online
 * build uses; only the transport differs. Standalone mode is also the demo: forms arrive
 * pre-filled with the reference patient (set3), and the history holds that patient's result.
 */

const REFERENCE_PATIENT = "Dinda A. (7 th)";

test.beforeEach(async ({ page }) => {
  await resetLocalData(page);
});

test("sign-in is pre-filled in demo mode", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByLabel("Email")).toHaveValue("dokter@toothfairy.id");
  await page.getByRole("button", { name: "Masuk" }).click();
  await expect(page.getByRole("link", { name: /Kasus Baru/i })).toBeVisible();
});

test("a fresh device's history holds the reference result, and it opens only once 3D is ready", async ({ page }) => {
  await loginAsDoctor(page);
  await page.getByRole("link", { name: new RegExp(REFERENCE_PATIENT.replace(/[().]/g, "\\$&")) }).click();

  // the loading screen covers the page until the dentition has loaded and drawn
  await expect(page.getByRole("status", { name: "Membuka hasil analisis" })).toBeVisible();
  await expect(page.getByRole("status", { name: "Membuka hasil analisis" })).toHaveCount(0, { timeout: 60_000 });
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect(page.getByText(/Diagnosis per Gigi/i).first()).toBeVisible({ timeout: 30_000 });
});

test("a case runs from anamnesa to results and lands in the history", async ({ page }) => {
  await loginAsDoctor(page);

  await page.getByRole("link", { name: /Kasus Baru/i }).click();
  await expect(page.getByLabel("Lokasi keluhan")).toHaveValue(/depan atas/);

  // Step 1 — pre-filled; rename so this case is distinguishable from the seeded one.
  await page.getByLabel("Nama Pasien (opsional)").fill("Rafi B.");
  await page.getByRole("button", { name: /^Lanjut$/ }).click();

  // Step 2 — pre-filled too; moving here must not have raised any validation error.
  await expect(page.getByLabel("Alasan kuat datang kali ini")).not.toHaveValue("");
  await expect(page.getByText(/wajib diisi/)).toHaveCount(0);
  await page.getByRole("button", { name: /Simpan & Lanjut ke Foto/i }).click();

  // --- upload: all six reference photos drop into their slots ---
  await expect(page.getByText(/Unggah Foto/i).first()).toBeVisible();
  await expect(page.getByText("6", { exact: true })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: /Unggah Foto/i }).click();

  // --- run ---
  await page.getByRole("button", { name: /Jalankan Analisis/i }).click();
  const loader = page.getByRole("status", { name: "Menganalisis citra pasien" });
  await expect(loader).toBeVisible();
  await expect(loader.getByRole("progressbar")).toBeVisible();

  // --- results: the loader stays up until the 3D scene is ready ---
  await expect(page).toHaveURL(/\/case\/case-/, { timeout: 60_000 });
  await expect(loader).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: /Rafi B\./i })).toBeVisible();

  const canvas = page.locator("canvas").first();
  await expect(canvas).toBeVisible();
  const shot = await canvas.screenshot();
  expect(shot.byteLength).toBeGreaterThan(5000);

  // The advisory documents render.
  await expect(page.getByText(/Diagnosis per Gigi/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Rencana Perawatan per Gigi/i).first()).toBeVisible();

  // ...and the case is now in the history, above the reference one.
  await page.goto("/");
  await expect(page.getByText("Rafi B.")).toBeVisible();
  await expect(page.getByText(REFERENCE_PATIENT)).toBeVisible();
});

test("resetting local data clears the history back to the reference case", async ({ page }) => {
  await loginAsDoctor(page);
  await page.getByRole("link", { name: /Kasus Baru/i }).click();
  await page.getByLabel("Nama Pasien (opsional)").fill("Sementara");
  await page.getByRole("button", { name: /^Lanjut$/ }).click();
  await page.getByRole("button", { name: /Simpan & Lanjut ke Foto/i }).click();
  await expect(page.getByText(/Unggah Foto/i).first()).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("Sementara")).toBeVisible();

  await resetLocalData(page);
  await loginAsDoctor(page);
  await expect(page.getByText(REFERENCE_PATIENT)).toBeVisible();
  await expect(page.getByText("Sementara")).toHaveCount(0);
});
