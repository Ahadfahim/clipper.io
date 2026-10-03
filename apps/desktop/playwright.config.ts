import { defineConfig, devices } from "@playwright/test";

const executablePath = process.env.PW_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    timezoneId: "UTC",
    locale: "en-US",
    contextOptions: { reducedMotion: "reduce" },
    trace: "retain-on-failure",
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    { name: "e2e", testMatch: /.*\.e2e\.ts/, use: { ...devices["Desktop Chrome"] } },
    { name: "screenshots", testMatch: /.*\.shots\.ts/, use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    // the fixture build: every API call is answered from public/fixtures (no Python needed)
    command: "pnpm exec vite build --mode fixtures && pnpm exec vite preview --mode fixtures --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
