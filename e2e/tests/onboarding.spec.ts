import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

const EMAIL = 'e2e-onboarding@e2e-user.dev';

// Not the suite's own User, who has finished Onboarding: this one starts at the X step.
test.use({ storageState: { cookies: [], origins: [] } });

/** Whether the stack under test has X's app keys, which decides if Onboarding has an X step. */
async function offersX(page: Page): Promise<boolean> {
  const instance = await (await page.request.get('/api/v1/instance')).json();
  return instance.x_connection === true;
}

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

test('the X step waits for X, then moves on once X is connected elsewhere', async ({ page }) => {
  test.skip(!(await offersX(page)), 'The stack has no X keys, so Onboarding has no X step.');
  await page.goto('/new');

  await expect(page).toHaveURL(/\/onboarding$/);
  const step = page.getByRole('region', { name: 'Connect your X account' });
  await expect(step.getByRole('button', { name: 'Connect X' })).toBeEnabled();
  await expect(
    page.getByRole('navigation', { name: 'Steps' }).locator('[aria-current="step"]'),
  ).toHaveText('2Connect X');

  runSeedScript('connect_x.py', [EMAIL]);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));

  await expect(
    page.getByRole('region', { name: 'Choose up to three authors to write like' }),
  ).toBeVisible();
});

test('an Instance without X starts Onboarding at the Persona step', async ({ page }) => {
  test.skip(await offersX(page), 'The stack has X keys, so Onboarding has an X step.');
  await page.goto('/new');

  await expect(
    page.getByRole('region', { name: 'Choose up to three authors to write like' }),
  ).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Steps' })).not.toContainText('Connect X');
});

test('the Persona step resumes after a reload, and Continue opens New post for good', async ({
  page,
}) => {
  runSeedScript('connect_x.py', [EMAIL]);
  await page.goto('/new');

  await expect(page).toHaveURL(/\/onboarding$/);
  const step = page.getByRole('region', { name: 'Choose up to three authors to write like' });
  const continueButton = step.getByRole('button', { name: 'Continue' });
  await expect(continueButton).toBeDisabled();

  const search = step.getByRole('combobox', { name: 'Find an author' });
  // A remembered miss, not the not-configured error: the stack may hold a real twitterapi.io
  // key, and the remembered miss answers without spending a call on it either way.
  await search.fill('@e2e_not_on_x');
  await step.getByRole('option', { name: 'Look up @e2e_not_on_x on X' }).click();
  await expect(step.getByText("@e2e_not_on_x isn't on X.")).toBeVisible();

  await search.fill('E2E Author');
  await search.press('Enter');
  const slots = step.getByRole('list', { name: /places taken/ });
  await expect(slots.getByText('@e2e_author')).toBeVisible();
  await expect(continueButton).toBeEnabled();

  await page.reload();
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(slots.getByText('@e2e_author')).toBeVisible();

  await continueButton.click();
  await expect(page).toHaveURL(/\/new$/);
  await expect(page.getByRole('heading', { level: 1, name: 'New post' })).toBeVisible();

  await page.goto('/persona');
  await page.getByRole('button', { name: 'Remove @e2e_author' }).click();
  await expect(page.getByRole('button', { name: 'Add an author' })).toHaveCount(3);
  await page.goto('/new');
  await expect(page.getByRole('heading', { level: 1, name: 'New post' })).toBeVisible();
  await expect(page).toHaveURL(/\/new$/);
});
