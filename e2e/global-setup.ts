import { chromium, type FullConfig } from '@playwright/test';
import * as path from 'node:path';
import { runSeedScript } from './backend';

const STORAGE_STATE = path.join(__dirname, 'storageState.json');
const APP_ORIGIN = 'http://localhost:5173';

function seedUserAndGetToken(): string {
  const out = runSeedScript('seed_user.py');
  const match = out.match(/E2E_ACCESS_TOKEN=(\S+)/);
  if (!match) throw new Error(`Seed script did not print a token. Output:\n${out}`);
  return match[1];
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  const token = seedUserAndGetToken();
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(APP_ORIGIN);
  await page.evaluate((t) => {
    // The frontend Session module's storage shape (`frontend/src/lib/session/store.ts`).
    // Far-future expiry so the frontend never refreshes or signs out mid-suite.
    localStorage.setItem(
      'pumpkit:session',
      JSON.stringify({ accessToken: t, expiresAt: '2099-01-01T00:00:00.000Z' }),
    );
  }, token);
  await context.storageState({ path: STORAGE_STATE });
  await browser.close();
}
