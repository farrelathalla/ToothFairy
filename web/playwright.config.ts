import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end config. Boots the whole stack, in dependency order:
 *
 *   1. ML service   (FastAPI, :8000) — MOCK_INFERENCE, so no model weights are needed
 *   2. API gateway  (Go, :8081)      — throwaway SQLite, seeded on boot
 *   3. Web app      (Next dev, :3000) with NEXT_PUBLIC_API_URL pointing at the gateway
 *
 * Running the real gateway rather than a stub is the point: these tests exercise the actual
 * auth, RBAC, upload and job-polling path the product ships with.
 *
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
      command: "python -m uvicorn app.main:app --port 8000",
      cwd: "../ml",
      port: 8000,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        MOCK_INFERENCE: "1",
        MOCK_STEP_DELAY: "0",
        LLM_ENABLED: "0",
        RAG_ENABLED: "0",
        INTERNAL_API_KEY: "e2e-internal-key",
      },
    },
    {
      command: "go run ./cmd/server",
      cwd: "../gateway",
      port: 8081,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        ENV: "test",
        // A throwaway database per run, so E2E never touches a developer's local data.
        DATABASE_URL: "./data/e2e.db",
        UPLOAD_DIR: "./data/e2e-uploads",
        JWT_SECRET: "e2e-secret-at-least-32-bytes-long-000",
        INTERNAL_API_KEY: "e2e-internal-key",
        ML_BASE_URL: "http://localhost:8000",
        CORS_ORIGINS: "http://localhost:3000",
        RATE_LIMIT_RPM: "0",
      },
    },
    {
      command: "npm run dev",
      cwd: ".",
      port: 3000,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { NEXT_PUBLIC_API_URL: "http://localhost:8081" },
    },
  ],
});
