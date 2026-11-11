import { chromium, type FullConfig } from '@playwright/test';
import * as path from 'node:path';
import { runSeedScript } from './backend';
import { assertEmulatedTarget } from './personal-safety';

const STORAGE_STATE = path.join(__dirname, 'storageState.json');

function seedUserAndGetToken(): string {
  const out = runSeedScript('seed_user.py');
  const match = out.match(/E2E_ACCESS_TOKEN=(\S+)/);
  if (!match) throw new Error(`Seed script did not print a token. Output:\n${out}`);
  return match[1];
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const appOrigin = config.projects[0].use.baseURL;
  if (!appOrigin) throw new Error('playwright.config.ts sets no baseURL');
  await assertEmulatedTarget(appOrigin);
  const token = seedUserAndGetToken();
  if (process.env.E2E_COUPONS === '1') {
    runSeedScript('coupon_user.py', ['check']);
  }
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(appOrigin);
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
