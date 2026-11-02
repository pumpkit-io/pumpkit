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

  await page.getByRole('button', { name: 'Sign in with Google' }).click();
  await page.waitForURL((url) => url.pathname === '/o/oauth2/v2/auth');
  test.skip(
    new URL(page.url()).hostname === 'accounts.google.com',
    'Google sign-in reaches Google itself: run the suite against scripts/dev-stack.',
  );
  await page.getByRole('button', { name: /test@example\.com/ }).click();

  await expect(page).not.toHaveURL(/\/(login|oauth\/google\/callback)/);
  const session = await page.evaluate(() => localStorage.getItem('pumpkit:session'));
  expect(JSON.parse(session ?? '{}').accessToken).toBeTruthy();
});
