import { test, expect } from "@playwright/test";
import { loginAsDoctor } from "./helpers";

// Screenshot the <canvas> element, not the page: a full-page shot does not composite the
// WebGL layer, so it would come back blank even when the scene renders correctly.
test("3D canvas renders across arch modes (screenshot artifacts)", async ({ page }, testInfo) => {
  await loginAsDoctor(page);
  await page.goto("/case/demo-set3");
  const canvas = page.locator("canvas").first();
  await expect(canvas).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2500); // let the GLB load + carve settle

  for (const arch of ["Bagian Atas", "Bagian Bawah", "Keduanya"]) {
    await page.getByRole("tab", { name: arch }).click();
    await page.waitForTimeout(1500);
    const outDir = process.env.CANVAS_SHOT_DIR;
    const shot = await canvas.screenshot(
      outDir ? { path: `${outDir}/canvas-${arch.replace(/\s+/g, "-")}.png` } : undefined
    );
    // a rendered dentition is not a blank frame: expect a non-trivial PNG
    expect(shot.byteLength).toBeGreaterThan(5000);
    await testInfo.attach(`canvas-${arch}`, { body: shot, contentType: "image/png" });
  }
});
