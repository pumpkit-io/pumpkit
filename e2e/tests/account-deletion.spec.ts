import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

// Leaver signs in through the X Emulator, so every run starts from a fresh account.
test.use({ storageState: { cookies: [], origins: [] } });

const LEAVER = 'Leaver (leaver@e2e-user.dev)';
const LEAVER_X_ID = '1004';

/** Signs in as Leaver on the login card and answers with the X Emulator's origin. */
async function signIn(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'Continue with X' }).click();
  await expect(page.getByRole('heading', { name: 'Authorize local X account' })).toBeVisible();
  const emulator = new URL(page.url()).origin;
  await page.getByRole('button', { name: LEAVER, exact: true }).click();
  return emulator;
}

async function profileId(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const session = JSON.parse(localStorage.getItem('pumpkit:session')!);
    const response = await fetch('/api/v1/users/me', {
      headers: { Authorization: `Bearer ${session.accessToken}` },
    });
    if (!response.ok) throw new Error('The signed-in profile was refused');
    return ((await response.json()) as { id: string }).id;
  });
}

async function revokes(page: Page, emulator: string): Promise<number> {
  const events: { kind: string; userId: string }[] = await (
    await page.request.get(`${emulator}/_pumpkit/events`)
  ).json();
  return events.filter((e) => e.kind === 'revoke' && e.userId === LEAVER_X_ID).length;
}

const MONTHLY = /^(Start trial|Subscribe): .*month/i;

async function openPaywall(page: Page) {
  // The Paywall's Plans are rate limited per client, so reload until they list.
  await expect(async () => {
    await page.goto('/subscribe');
    await expect(page.getByRole('button', { name: MONTHLY })).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 70_000 });
}

async function subscribe(page: Page) {
  await openPaywall(page);
  for (const box of await page.getByRole('checkbox').all()) await box.check();
  await page.getByRole('button', { name: MONTHLY }).click();
  await page.getByRole('button', { name: 'Pay' }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
}

test('a User deletes their account from Settings and signing in again starts a fresh one', async ({
  page,
}) => {
  runSeedScript('leaver.py', ['reset']);
  // The stack's model is real and costs money, so the draft is answered here.
  await page.route('**/api/v1/positioning/draft', (route) =>
    route.fulfill({ json: { text: 'I post about leaving.', reason: null, can_draft: true } }),
  );
  await page.goto('/login');
  const emulator = await signIn(page);
  await expect(page).toHaveURL(/\/subscribe$/);
  const original = await profileId(page);
  const revokedBefore = await revokes(page, emulator);
  await subscribe(page);
  const step = page.getByRole('region', { name: 'Who you are on X' });
  await expect(step.getByRole('textbox', { name: 'Who you are on X' })).toHaveValue(
    'I post about leaving.',
  );
  await step.getByRole('button', { name: 'Continue' }).click();
  await expect(page).toHaveURL(/\/new$/);

  await page.goto('/settings');
  const section = page.getByRole('region', { name: 'Delete account' });
  await section.getByRole('button', { name: 'Delete account' }).click();
  const dialog = page.getByRole('alertdialog', { name: 'Delete your account?' });
  await expect(dialog.getByText('Posts already on X stay on X.')).toBeVisible();
  const confirm = dialog.getByRole('button', { name: 'Delete my account' });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel('Type @leaver to confirm').fill('@leaver');
  await confirm.click();
  // Until deleting ends a running subscription itself, the User is asked to cancel it first.
  await expect(dialog.getByRole('alert')).toContainText('Your subscription is still running.');

  runSeedScript('leaver.py', ['end']);
  await confirm.click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole('status').filter({ hasText: 'Your account is deleted.' }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('pumpkit:session'))).toBeNull();
  // The revoke runs in the background after the deletion answers.
  await expect.poll(() => revokes(page, emulator)).toBe(revokedBefore + 1);

  await signIn(page);
  await expect(page).toHaveURL(/\/subscribe$/);
  expect(await profileId(page)).not.toBe(original);
  await openPaywall(page);
  await expect(page.getByRole('button', { name: /^Start trial: / })).toHaveCount(0);
});
