import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E 設定。
 *
 * 設計方針 (docs/architecture/e2e-strategy.md §1.2 参照):
 *   - retries=0 — flaky を黙って隠さない。失敗は spec を直すか quarantine。
 *   - workers=1 — 共有 DB を持つ実スタックなので並列化は Phase 1 では避ける。
 *   - trace=on / video=retain-on-failure / screenshot=only-on-failure
 *     失敗時の診断を最大化する。
 *   - baseURL は env から (`BASE_URL_E2E`)。
 *     compose では `http://traefik`、ローカル debug 時は `http://localhost:8081`。
 */

const baseURL = process.env.BASE_URL_E2E ?? "http://traefik";

export default defineConfig({
  testDir: "./tests",
  outputDir: "./results/test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [
    ["list"],
    ["html", { outputFolder: "results/html-report", open: "never" }],
    ["junit", { outputFile: "results/junit.xml" }],
  ],
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL,
    trace: "on",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 5_000,
    navigationTimeout: 15_000,
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
