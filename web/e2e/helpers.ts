import { Page, expect } from "@playwright/test";
import path from "node:path";

export const ADMIN = { email: "admin@toothfairy.com", password: "admin123" };
export const DOCTOR = { email: "doctor@toothfairy.com", password: "doctor123" };

const TP = path.resolve(__dirname, "../../test_pic");
export const INTRAORAL = path.join(TP, "intraoral.jpg");
export const PANORAMIC = path.join(TP, "panoramic.png");

export async function login(page: Page, { email, password }: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Kata Sandi").fill(password);
  await page.getByRole("button", { name: "Masuk" }).click();
}

export async function loginAsDoctor(page: Page) {
  await login(page, DOCTOR);
  await expect(page).toHaveURL(/\/$|\/#/);
  await expect(page.getByRole("link", { name: /Kasus Baru/i })).toBeVisible();
}
