import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

test.use({ storageState: { cookies: [], origins: [] } });

const DRAFTED =
  "I'm a solo founder building a pricing tool. I post about pricing for people starting their first SaaS.";
const ADDED = ' I post to earn sign-ups.';
const NOT_READ = "We couldn't read your X profile. Write it yourself, a few sentences is enough.";

const MONTHLY = /^(Start trial|Subscribe): .*month/i;

/** Subscribes through the Stripe Emulator's Checkout, which ends on Onboarding. */
async function subscribe(page: Page) {
  // The Paywall's Plans are rate limited per client, so reload until they list.
  await expect(async () => {
    await page.goto('/subscribe');
    await expect(page.getByRole('button', { name: MONTHLY })).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 70_000 });
  for (const box of await page.getByRole('checkbox').all()) await box.check();
  await page.getByRole('button', { name: MONTHLY }).click();
  await page.getByRole('button', { name: 'Pay' }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
}

// This User has no Positioning and has not finished Onboarding.
test.describe('a seeded User', () => {
  test.beforeEach(async ({ page }) => {
    const out = runSeedScript('onboarding_user.py');
    const token = out.match(/E2E_ACCESS_TOKEN=(\S+)/)?.[1];
    if (!token) throw new Error(`Seed script did not print a token. Output:\n${out}`);
    await page.addInitScript((t) => {
      localStorage.setItem(
        'pumpkit:session',
        JSON.stringify({ accessToken: t, expiresAt: '2099-01-01T00:00:00.000Z' }),
      );
      localStorage.setItem('pumpkit:analytics-consent', JSON.stringify('denied'));
    }, token);
  });

  test('Onboarding starts directly at Persona without a separate X task', async ({ page }) => {
    await page.goto('/new');
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Who you are on X' })).toBeVisible();
    await expect(
      page.getByText(/^Pumpkit plans every post around this\. Two or three/),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: /draft again/i })).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'Steps' })).not.toContainText('Connect X');
  });

  test('the Persona step drafts the positioning, and Continue saves the edit and opens New post for good', async ({
    page,
  }) => {
    // The stack's model is real and costs money, so the draft the server keeps is answered here.
    let ready = false;
    await page.route('**/api/v1/positioning/draft/start', (route) =>
      route.fulfill({ status: 202, body: '' }),
    );
    await page.route('**/api/v1/positioning', (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const draft = ready
        ? { state: 'ready', text: DRAFTED, reason: null }
        : { state: 'running', text: null, reason: null };
      return route.fulfill({ json: { text: null, saved_at: null, draft } });
    });
    await page.goto('/new');

    await expect(page).toHaveURL(/\/onboarding$/);
    const step = page.getByRole('region', { name: 'Who you are on X' });
    const field = step.getByRole('textbox', { name: 'Who you are on X' });
    const continueButton = step.getByRole('button', { name: 'Continue' });
    await expect(field).toHaveAccessibleDescription(/^Reading your X profile…/);
    await expect(field).toBeDisabled();
    await expect(continueButton).toBeDisabled();

    ready = true;
    await expect(field).toHaveValue(DRAFTED);
    await field.press('End');
    await field.pressSequentially(ADDED);
    await continueButton.click();

    await expect(page).toHaveURL(/\/new$/);
    await page.unroute('**/api/v1/positioning');
    await expect(page.getByRole('heading', { level: 1, name: 'New post' })).toBeVisible();
    await page.goto('/persona');
    await expect(page.getByRole('textbox', { name: 'Who you are on X' })).toHaveValue(
      `${DRAFTED}${ADDED}`,
    );
    await page.goto('/new');
    await expect(page).toHaveURL(/\/new$/);
  });

  test('the Persona step opens empty with the reason when no draft can be made', async ({
    page,
  }) => {
    // Without an X connection the backend reads nothing and asks no model.
    await page.goto('/onboarding');

    const step = page.getByRole('region', { name: 'Who you are on X' });
    const field = step.getByRole('textbox', { name: 'Who you are on X' });
    await expect(step.getByText(NOT_READ)).toBeVisible();
    await expect(field).toBeEnabled();
    await expect(field).toHaveValue('');
    const continueButton = step.getByRole('button', { name: 'Continue' });
    await expect(continueButton).toBeDisabled();

    await page.reload();
    await expect(page).toHaveURL(/\/onboarding$/);
    await field.fill('I post about pricing for first-time founders.');
    await continueButton.click();

    await expect(page).toHaveURL(/\/new$/);
    await expect(page.getByRole('heading', { level: 1, name: 'New post' })).toBeVisible();
  });
});

// Leaver signs in through the X Emulator, so every run starts from a fresh account.
test.describe('signing in with X', () => {
  test('starts the draft at sign-in, and the Persona step after the Paywall waits for it instead of starting another', async ({
    page,
  }) => {
    runSeedScript('leaver.py');
    // The stack's model is real and costs money, so the draft the server keeps is answered here.
    let starts = 0;
    let ready = false;
    await page.route('**/api/v1/positioning/draft/start', (route) => {
      starts += 1;
      return route.fulfill({ status: 202, body: '' });
    });
    await page.route('**/api/v1/positioning', (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const draft =
        starts === 0
          ? null
          : ready
            ? { state: 'ready', text: DRAFTED, reason: null }
            : { state: 'running', text: null, reason: null };
      return route.fulfill({ json: { text: null, saved_at: null, draft } });
    });

    await page.goto('/login');
    await page.getByRole('button', { name: 'Continue with X' }).click();
    await page.getByRole('button', { name: 'Leaver (leaver@e2e-user.dev)', exact: true }).click();
    await expect(page).toHaveURL(/\/subscribe$/);
    await expect.poll(() => starts).toBe(1);

    await subscribe(page);
    const step = page.getByRole('region', { name: 'Who you are on X' });
    const field = step.getByRole('textbox', { name: 'Who you are on X' });
    await expect(field).toHaveAccessibleDescription(/^Reading your X profile…/);
    ready = true;
    await expect(field).toHaveValue(DRAFTED);
    expect(starts).toBe(1);
  });
});
