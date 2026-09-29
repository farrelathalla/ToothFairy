import { test, expect } from "@playwright/test";
import { ADMIN, login } from "./helpers";

test("admin creates a doctor who can then log in", async ({ page }) => {
  const email = `dokter${Date.now()}@klinik.com`;

  await login(page, ADMIN);
  await expect(page).toHaveURL(/\/admin/);

  await page.getByRole("button", { name: /Akun Baru/i }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Email").fill(email);
  await dialog.getByLabel("Nama").fill("Dokter E2E");
  await dialog.getByLabel(/Kata Sandi/i).fill("rahasia123");
  await dialog.getByRole("button", { name: /Buat Akun/i }).click();

  // new account row appears
  await expect(page.getByText(email)).toBeVisible();

  // log out, then the new doctor can log in and reach the doctor home
  await page.getByRole("button", { name: /Keluar/i }).click();
  await login(page, { email, password: "rahasia123" });
  await expect(page).toHaveURL("http://localhost:3000/");
  await expect(page.getByRole("link", { name: /Kasus Baru/i })).toBeVisible();
});

test("admin visiting the doctor home is bounced to /admin", async ({ page }) => {
  await login(page, ADMIN);
  await expect(page).toHaveURL(/\/admin/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/admin/);
});
