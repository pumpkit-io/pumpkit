import { expect, test } from '@playwright/test';
import { runSeedScript } from '../backend';

// This User has no Positioning and has not finished Onboarding.
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

const DRAFTED =
  "I'm a solo founder building a pricing tool. I post about pricing for people starting their first SaaS.";
const ADDED = ' I post to earn sign-ups.';
const NOT_READ = "We couldn't read your X profile. Write it yourself, a few sentences is enough.";

test('Onboarding starts directly at Persona without a separate X task', async ({ page }) => {
  await page.goto('/new');
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Who you are on X' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Steps' })).not.toContainText('Connect X');
});

test('the Persona step drafts the positioning, and Continue saves the edit and opens New post for good', async ({
  page,
}) => {
  // The stack's model is real and costs money, so the draft is answered here.
  let answer: () => void = () => {};
  const answered = new Promise<void>((resolve) => (answer = resolve));
  await page.route('**/api/v1/positioning/draft', async (route) => {
    await answered;
    await route.fulfill({ json: { text: DRAFTED, reason: null, can_draft: true } });
  });
  await page.goto('/new');

  await expect(page).toHaveURL(/\/onboarding$/);
  const step = page.getByRole('region', { name: 'Who you are on X' });
  const field = step.getByRole('textbox', { name: 'Who you are on X' });
  const continueButton = step.getByRole('button', { name: 'Continue' });
  await expect(field).toHaveAttribute('placeholder', 'Reading your X profile…');
  await expect(field).toBeDisabled();
  await expect(continueButton).toBeDisabled();

  answer();
  await expect(field).toHaveValue(DRAFTED);
  await field.press('End');
  await field.pressSequentially(ADDED);
  await continueButton.click();

  await expect(page).toHaveURL(/\/new$/);
  await expect(page.getByRole('heading', { level: 1, name: 'New post' })).toBeVisible();
  await page.goto('/persona');
  await expect(page.getByRole('textbox', { name: 'Who you are on X' })).toHaveValue(
    `${DRAFTED}${ADDED}`,
  );
  await page.goto('/new');
  await expect(page).toHaveURL(/\/new$/);
});

test('the Persona step opens empty with the reason when no draft can be made', async ({ page }) => {
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
