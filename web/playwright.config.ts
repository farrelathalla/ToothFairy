import { defineConfig, devices } from "@playwright/test";

/**
 * E2E config. Boots two servers:
 *  - backend (FastAPI) via ../backend/e2e_serve.py — MOCK_INFERENCE, fresh seeded DB, :8000
 *  - frontend (next dev) with NEXT_PUBLIC_API_URL pointing at the backend, :3000
 * Mobile-first: tests run in a Pixel-5 viewport.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    ...devices["Pixel 5"],
  },
  webServer: [
    {
      command: "python e2e_serve.py",
      cwd: "../backend",
      port: 8000,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run dev",
      cwd: ".",
      port: 3000,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { NEXT_PUBLIC_API_URL: "http://localhost:8000" },
    },
  ],
});
