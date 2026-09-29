import { test, expect } from "@playwright/test";
import { ADMIN, login } from "./helpers";

test("a fresh doctor cannot open another doctor's case", async ({ page }) => {
  // create a brand-new doctor (owns no cases) via admin
  const email = `other${Date.now()}@klinik.com`;
  await login(page, ADMIN);
  await page.getByRole("button", { name: /Akun Baru/i }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByLabel("Nama").fill("Dokter Lain");
  await dialog.getByLabel(/Kata Sandi/i).fill("rahasia123");
  await dialog.getByRole("button", { name: /Buat Akun/i }).click();
  await expect(page.getByText(email)).toBeVisible();
  await page.getByRole("button", { name: /Keluar/i }).click();

  // log in as the new doctor and try to open a case owned by the seeded doctor
  await login(page, { email, password: "rahasia123" });
  await expect(page).toHaveURL("http://localhost:3000/");
  await page.goto("/case/demo-set1");

  // owner-scoped 404 → results page surfaces the load error, no canvas
  await expect(page.getByText(/Gagal memuat kasus|tidak ditemukan/i)).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("canvas")).toHaveCount(0);
});
