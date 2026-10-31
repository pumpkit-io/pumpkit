import { expect, test } from '@playwright/test';
import { runSeedScript } from '../backend';

// Not the suite's own User, who has finished Onboarding: this one starts at the Persona step.
test.use({ storageState: { cookies: [], origins: [] } });

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

test('the Persona step resumes after a reload, and Continue opens New post for good', async ({
  page,
}) => {
  await page.goto('/new');

  await expect(page).toHaveURL(/\/onboarding$/);
  const step = page.getByRole('region', { name: 'Choose up to three authors to write like' });
  const continueButton = step.getByRole('button', { name: 'Continue' });
  await expect(continueButton).toBeDisabled();

  const search = step.getByRole('combobox', { name: 'Find an author' });
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
