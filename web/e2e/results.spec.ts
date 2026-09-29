import { test, expect } from "@playwright/test";
import { loginAsDoctor } from "./helpers";

// The seeded severe demo case (rampant caries, has hidden lower-arch lesions).
const CASE = "demo-set3";
const DATASET = "set3"; // demo-set3 points at the precomputed set3 results dir

test.beforeEach(async ({ page }) => {
  await loginAsDoctor(page);
  await page.goto(`/case/${CASE}`);
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
});

test("arch tabs switch the view", async ({ page }) => {
  await page.getByRole("tab", { name: "Bagian Bawah" }).click();
  await expect(page.getByRole("tab", { name: "Bagian Bawah" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Keduanya" }).click();
  await expect(page.getByRole("tab", { name: "Keduanya" })).toHaveAttribute("aria-selected", "true");
});

test("caries summary counts match detections.json", async ({ page }) => {
  const det = await page.evaluate(async (d) => {
    const r = await fetch(`/results/${d}/detections.json`);
    return r.json();
  }, DATASET);
  const affected = Object.values<any>(det.teeth).filter((t: any) => t.severity > 0);

  // total affected shown in the summary
  await expect(page.getByText("Gigi berkaries")).toBeVisible();
  await expect(page.getByText(String(affected.length), { exact: true }).first()).toBeVisible();
});

test("a hidden-lesion badge is shown for the severe case", async ({ page }) => {
  await expect(page.getByText(/tersembunyi/i).first()).toBeVisible();
});

test("the model overlay gallery opens a lightbox", async ({ page }) => {
  const card = page.getByTestId("gallery-card").first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.click();
  await expect(page.getByRole("dialog")).toBeVisible();
});
