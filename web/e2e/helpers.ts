import { Page, expect } from "@playwright/test";
import path from "node:path";

/**
 * Standalone mode has no account store, so any well-formed sign-in opens a local session.
 * These are the credentials the specs use — they carry no privilege of their own.
 */
export const DOCTOR = { email: "drg.demo@klinik.id", password: "demo1234" };

const SAMPLES = path.resolve(__dirname, "../../assets/samples");
export const UP = path.join(SAMPLES, "set3", "up3.png");
export const FRONT = path.join(SAMPLES, "set3", "front3.png");
export const PANORAMIC = path.join(SAMPLES, "set3", "STS24_Train_Labeled_0012.jpg");

/** Clears any local session/history left by a previous spec. */
export async function resetLocalData(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: /Atur ulang data lokal/i }).click();
  await expect(page.getByLabel("Email")).toBeVisible();
}

export async function login(page: Page, who = DOCTOR) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Kata Sandi").fill(who.password);
  await page.getByRole("button", { name: "Masuk" }).click();
}

export async function loginAsDoctor(page: Page) {
  await login(page);
  await expect(page.getByRole("link", { name: /Kasus Baru/i })).toBeVisible();
}
