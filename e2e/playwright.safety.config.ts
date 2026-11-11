import { defineConfig } from '@playwright/test';

export default defineConfig({ testDir: './checks', workers: 1, reporter: 'list' });
