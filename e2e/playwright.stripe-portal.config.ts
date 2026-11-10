import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: 'stripe-portal-live.spec.ts',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    headless: false,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    storageState: { cookies: [], origins: [] },
  },
});
