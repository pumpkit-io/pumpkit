import { expect, test } from '@playwright/test';

// Signs in from scratch, through the Google Emulator's sign-in page that scripts/dev-stack runs.
test.use({ storageState: { cookies: [], origins: [] } });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('pumpkit:analytics-consent', JSON.stringify('denied'));
  });
});

test('signing in with Google through the Emulator starts a session', async ({ page }) => {
  const instance = await (await page.request.get('/api/v1/instance')).json();
  test.skip(!instance.sign_in_methods.includes('google'), 'The stack has no Google sign-in.');
  await page.goto('/login');

  const appOrigin = new URL(page.url()).origin;
  await page.getByRole('button', { name: 'Sign in with Google' }).click();
  // Real Google redirects on from its authorize URL, so wait only for leaving the app.
  await page.waitForURL((url) => url.origin !== appOrigin);
  test.skip(
    new URL(page.url()).hostname.endsWith('google.com'),
    'Google sign-in reaches Google itself: run the suite against scripts/dev-stack.',
  );
  await page.getByRole('button', { name: /test@example\.com/ }).click();

  // A new User's first stop: the Emulator's prices carry no lookup key, so the Paywall offers no Plans.
  await expect(page).toHaveURL(/\/(subscribe|onboarding)$/);
  const session = await page.evaluate(() => localStorage.getItem('pumpkit:session'));
  expect(JSON.parse(session ?? '{}').accessToken).toBeTruthy();
});
