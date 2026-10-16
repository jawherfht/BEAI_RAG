import { defineConfig } from "@playwright/test";

/**
 * E2E for screen B against the real stack: rag-api on :8000 + ingestion worker + embedding
 * server + LLM (see `make e2e`). Ingestion on CPU is slow, hence the generous timeouts.
 * PLAYWRIGHT_CHROMIUM lets CI/dev point at a pre-installed Chromium.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 10 * 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM } : {},
  },
  webServer: {
    command: "npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
