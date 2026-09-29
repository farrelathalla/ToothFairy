import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end config for standalone mode.
 *
 * Only the web app is booted: `NEXT_PUBLIC_STANDALONE` makes `lib/standalone.js` answer the
 * API from the browser, so these tests cover the offline path a clinic tablet actually takes
 * when the gateway is unreachable — sign-in, case creation, upload, analysis progress, and
 * the results view — with no gateway and no ML service running.
 *
 * Mobile-first: tests run in a Pixel-5 viewport.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    ...devices["Pixel 5"],
  },
  webServer: [
    {
      command: "npm run dev",
      cwd: ".",
      port: 3000,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { NEXT_PUBLIC_STANDALONE: "1" },
    },
  ],
});
