import { test, expect } from "@playwright/test";
import { loginAsDoctor } from "./helpers";

test("the 4 seeded demo cases appear in Riwayat and open", async ({ page }) => {
  await loginAsDoctor(page);

  // seeded demo patients
  for (const name of ["Ananda R. (7 th)", "Bima S. (6 th)", "Citra P. (8 th)", "Dinda A. (7 th)"]) {
    await expect(page.getByText(name)).toBeVisible();
  }

  // opening one renders its results
  await page.getByText("Dinda A. (7 th)").click();
  await expect(page).toHaveURL(/\/case\/demo-set3/);
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  // exact: the advisory markdown also has "Diagnosis per Gigi" and "Diagnosis Banding …"
  await expect(page.getByRole("heading", { name: "Diagnosis", exact: true })).toBeVisible();
});
