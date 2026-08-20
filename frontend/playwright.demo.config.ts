import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PORT ?? 3000);
// Next.js development resources enforce their origin strictly. Using localhost
// here matches the dev server and avoids the browser treating 127.0.0.1 as a
// different origin during the recording run.
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${port}`;

export default defineConfig({
  testDir: "./tests/demo",
  outputDir: "../demo-output/playwright",
  timeout: 300_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1440, height: 900 },
    locale: "en-US",
    trace: "off",
    screenshot: "only-on-failure",
    video: {
      mode: "on",
      size: { width: 1440, height: 900 },
    },
  },
  projects: [
    {
      name: "chromium-demo",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: process.env.PLAYWRIGHT_DEV_CMD ?? "npm run dev",
        port,
        reuseExistingServer: false,
        timeout: 120_000,
      },
});
