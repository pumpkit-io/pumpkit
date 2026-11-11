import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: 'local-x-relay.spec.ts',
  workers: 1,
  reporter: 'list',
});
