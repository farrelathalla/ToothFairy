import { test, expect } from "@playwright/test";
import { loginAsDoctor } from "./helpers";

// Verify the rebuilt gingiva (gums.glb) renders in the REAL three.js canvas with the gum toggled ON,
// across arch modes. Screenshots the <canvas> element (full-page doesn't composite WebGL, CLAUDE.md §8).
test("gusi renders on the real canvas", async ({ page }, testInfo) => {
  test.setTimeout(120_000); // first next-dev compile of the case page can be slow
  await loginAsDoctor(page);
  await page.goto("/case/demo-set3");
  const canvas = page.locator("canvas").first();
  await expect(canvas).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2500);

  // frontal "both" view (matches image.png), then turn the gum ON
  await page.getByRole("tab", { name: "Keduanya" }).click();
  await page.waitForTimeout(1000);
  await page.getByRole("button", { name: /Gusi:/ }).click();
  await page.waitForTimeout(3000);

  // Clip a viewport screenshot to the canvas box (a non-fullPage page.screenshot composites WebGL
  // and doesn't wait for element "stability", which the continuously-rendering canvas never reaches).
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  const outDir = process.env.CANVAS_SHOT_DIR;
  const shot = await page.screenshot({
    clip: { x: box!.x, y: box!.y, width: box!.width, height: box!.height },
    path: outDir ? `${outDir}/appgum-both.png` : undefined,
  });
  expect(shot.byteLength).toBeGreaterThan(5000);
  await testInfo.attach("appgum-both", { body: shot, contentType: "image/png" });
});
