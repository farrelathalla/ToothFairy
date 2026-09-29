import { test, expect } from "@playwright/test";
import { loginAsDoctor, INTRAORAL, PANORAMIC } from "./helpers";

test("doctor runs a new case end-to-end (mock inference) to the results view", async ({ page }) => {
  await loginAsDoctor(page);

  await page.getByRole("link", { name: /Kasus Baru/i }).click();
  await expect(page).toHaveURL(/\/case\/new/);

  // Step 1 — Sacred Seven (fill required fields)
  await page.getByLabel("Nama Pasien (opsional)").fill("Pasien E2E");
  await page.getByLabel(/^Lokasi keluhan/).fill("Geraham kiri bawah");
  await page.getByLabel(/^Kualitas nyeri/).fill("Cenut-cenut");
  await page.getByRole("button", { name: /^Lanjut/ }).click();

  // Step 2 — Riwayat (required: alasan kuat)
  await page.getByLabel(/^Alasan kuat datang/).fill("Nyeri makin parah");
  await page.getByRole("button", { name: /Simpan & Lanjut ke Foto/i }).click();

  // Upload 6 slots (reuse the shipped sample images)
  await page.getByLabel("Rahang Atas (oklusal)").setInputFiles(INTRAORAL);
  await page.getByLabel("Rahang Bawah (oklusal)").setInputFiles(INTRAORAL);
  await page.getByLabel("Depan").setInputFiles(INTRAORAL);
  await page.getByLabel("Samping Kiri").setInputFiles(INTRAORAL);
  await page.getByLabel("Samping Kanan").setInputFiles(INTRAORAL);
  await page.getByLabel("Panoramik").setInputFiles(PANORAMIC);

  await page.getByRole("button", { name: /Unggah Foto/i }).click();

  // Run inference (mock) → progress → results
  await page.getByRole("button", { name: /Jalankan Analisis/i }).click();
  await expect(page).toHaveURL(/\/case\/case-/, { timeout: 30_000 });

  // Results render: 3D canvas + caries summary + LLM cards
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Gigi berkaries")).toBeVisible();
  // E2E runs with LLM_ENABLED=0, so the advisory is the deterministic stub, whose headings are
  // "Diagnosis (sementara)" / "Rekomendasi Penanganan (sementara)". Match the prefix so the
  // assertion holds for both the stub and real LLM output.
  await expect(page.getByRole("heading", { name: /^Diagnosis\b/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Rekomendasi Penanganan/i })).toBeVisible();
});
