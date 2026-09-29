import { test, expect } from "@playwright/test";
import { ADMIN, DOCTOR, login } from "./helpers";

test("unauthenticated visit is redirected to /login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});

test("wrong credentials show an error", async ({ page }) => {
  await login(page, { email: DOCTOR.email, password: "salahsalah" });
  await expect(page.getByText(/Email atau kata sandi salah/i).first()).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("admin logs in and lands on /admin", async ({ page }) => {
  await login(page, ADMIN);
  await expect(page).toHaveURL(/\/admin/);
});

test("doctor logs in and lands on the home", async ({ page }) => {
  await login(page, DOCTOR);
  await expect(page).toHaveURL("http://localhost:3000/");
  await expect(page.getByRole("link", { name: /Kasus Baru/i })).toBeVisible();
});
