import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.js"],
    include: ["tests/**/*.{test,spec}.{js,jsx}"],
    exclude: ["e2e/**", "node_modules/**"],
    css: false,
    // The unit suite exercises the *network* client; standalone mode has its own tests
    // (tests/standalone.test.js) that enable it explicitly.
    env: { NEXT_PUBLIC_STANDALONE: "0" },
  },
});
