import { defineConfig, devices } from '@playwright/test';

// E2E tests run against a running RequestHub API that serves the built UI (Development auth mode).
const baseURL = process.env.BASE_URL ?? 'http://localhost:5080';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  // Tests share one demo database that global setup resets, so run them one at a time.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
