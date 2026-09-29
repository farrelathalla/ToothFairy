import { test, expect } from "@playwright/test";

import { FRONT, PANORAMIC, UP, loginAsDoctor, resetLocalData } from "./helpers";

/**
 * The offline path end to end: sign in, create a case, upload photos, watch the analysis
 * progress, and read the results — with no gateway and no ML service running.
 *
 * Everything here goes through the same screens and the same `lib/api.js` calls the online
 * build uses; only the transport differs.
 */

test.beforeEach(async ({ page }) => {
  await resetLocalData(page);
});

test("history starts empty on a fresh device", async ({ page }) => {
  await loginAsDoctor(page);
  await expect(page.getByText("Belum ada riwayat kasus.")).toBeVisible();
});

test("a case runs from anamnesa to results and lands in the history", async ({ page }) => {
  await loginAsDoctor(page);

  await page.getByRole("link", { name: /Kasus Baru/i }).click();
  await expect(page.getByLabel("Lokasi keluhan")).toBeVisible();

  // Step 1 — the complaint.
  await page.getByLabel("Nama Pasien (opsional)").fill("Dinda A.");
  await page.getByLabel("Lokasi keluhan").fill("Hampir seluruh kuadran, terparah gigi depan atas");
  await page.getByLabel("Kualitas nyeri").fill("Nyeri spontan, berdenyut");
  await page.getByRole("button", { name: /^Lanjut$/ }).click();

  // Step 2 — the history.
  await page.getByLabel("Alasan kuat datang kali ini").fill("Anak kesakitan saat makan");
  await page.getByRole("button", { name: /Simpan & Lanjut ke Foto/i }).click();

  // --- upload ---
  await expect(page.getByText(/Unggah Foto/i).first()).toBeVisible();
  await page.setInputFiles('input[aria-label="Rahang Atas (oklusal)"]', UP);
  await page.setInputFiles('input[aria-label="Depan"]', FRONT);
  await page.setInputFiles('input[aria-label="Panoramik"]', PANORAMIC);
  await page.getByRole("button", { name: /Unggah Foto/i }).click();

  // --- run ---
  await expect(page.getByRole("button", { name: /Jalankan Analisis/i })).toBeVisible();
  await page.getByRole("button", { name: /Jalankan Analisis/i }).click();
  await expect(page.getByText(/Menganalisis citra/i)).toBeVisible();

  // --- results ---
  await expect(page).toHaveURL(/\/case\/case-/, { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: /Dinda A\./i })).toBeVisible();

  // The 3D scene mounts and draws.
  const canvas = page.locator("canvas").first();
  await expect(canvas).toBeVisible({ timeout: 40_000 });
  await page.waitForTimeout(2500);
  const shot = await canvas.screenshot();
  expect(shot.byteLength).toBeGreaterThan(5000);

  // The advisory documents render.
  await expect(page.getByText(/Diagnosis per Gigi/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Rencana Perawatan per Gigi/i).first()).toBeVisible();

  // ...and the case is now in the history.
  await page.goto("/");
  await expect(page.getByText("Dinda A.")).toBeVisible();
  await expect(page.getByText("Belum ada riwayat kasus.")).toHaveCount(0);
});

test("resetting local data clears the history", async ({ page }) => {
  await loginAsDoctor(page);
  await page.getByRole("link", { name: /Kasus Baru/i }).click();
  await page.getByLabel("Nama Pasien (opsional)").fill("Sementara");
  await page.getByLabel("Lokasi keluhan").fill("Geraham kiri bawah");
  await page.getByLabel("Kualitas nyeri").fill("Cenut-cenut");
  await page.getByRole("button", { name: /^Lanjut$/ }).click();
  await page.getByLabel("Alasan kuat datang kali ini").fill("Kontrol rutin");
  await page.getByRole("button", { name: /Simpan & Lanjut ke Foto/i }).click();
  await expect(page.getByText(/Unggah Foto/i).first()).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("Sementara")).toBeVisible();

  await resetLocalData(page);
  await loginAsDoctor(page);
  await expect(page.getByText("Belum ada riwayat kasus.")).toBeVisible();
});
