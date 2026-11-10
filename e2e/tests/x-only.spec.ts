import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

const E2E_ACCOUNT = 'E2E User (e2e@e2e-user.dev)';

test.use({ storageState: { cookies: [], origins: [] } });

async function continueWithX(page: Page, account: string) {
  await page.getByRole('button', { name: 'Continue with X' }).click();
  await expect(page.getByRole('heading', { name: 'Authorize local X account' })).toBeVisible();
  await page.getByRole('button', { name: account, exact: true }).click();
}

async function signIn(page: Page, account = E2E_ACCOUNT) {
  await page.goto('/login');
  await continueWithX(page, account);
}

async function profile(page: Page) {
  return page.evaluate(async () => {
    const session = JSON.parse(localStorage.getItem('pumpkit:session')!);
    const response = await fetch('/api/v1/users/me', {
      headers: { Authorization: `Bearer ${session.accessToken}` },
    });
    if (!response.ok) throw new Error('The signed-in profile was refused');
    return response.json() as Promise<{ id: string; first_name: string; x_handle: string }>;
  });
}

test('fresh and returning X sign-in keeps the same account and opens the Paywall before Persona', async ({
  page,
}) => {
  await signIn(page, 'Ada (ada@e2e-user.dev)');
  await expect(page).toHaveURL(/\/subscribe$/);
  const first = await profile(page);
  expect(first.x_handle).toBe('ada');
  await page.context().clearCookies();
  await page.evaluate(() => localStorage.removeItem('pumpkit:session'));
  await signIn(page, 'Ada (ada@e2e-user.dev)');
  await expect(page).toHaveURL(/\/subscribe$/);
  expect((await profile(page)).id).toBe(first.id);
  await expect(page.getByRole('button', { name: 'Connect X', exact: true })).toHaveCount(0);
});

test('pending app consent survives missing email and cancellation, then completes after X sign-in', async ({
  page,
  baseURL,
}) => {
  runSeedScript('seed_user.py');
  const redirect = 'http://127.0.0.1:49199/callback';
  const registration = await page.request.post('/api/v1/oauth/register', {
    data: {
      redirect_uris: [redirect],
      token_endpoint_auth_method: 'none',
      client_name: 'Browser smoke app',
    },
  });
  expect(registration.status()).toBe(201);
  const { client_id: clientId } = await registration.json();
  const started = await page.request.get('/api/v1/oauth/authorize', {
    params: {
      client_id: clientId,
      response_type: 'code',
      redirect_uri: redirect,
      code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
      code_challenge_method: 'S256',
      state: 'browser-smoke',
    },
    maxRedirects: 0,
  });
  expect(started.status()).toBe(303);
  const consent = new URL(started.headers().location, baseURL).toString();
  await page.goto(consent);
  await expect(page.getByRole('button', { name: 'Continue with X' })).toBeVisible();
  await continueWithX(page, 'No email (no confirmed email)');
  await expect(page.getByRole('alert')).toContainText('Confirm an email address on X');
  expect(await page.evaluate(() => localStorage.getItem('pumpkit:session'))).toBeNull();
  await continueWithX(page, 'Cancel');
  await expect(page.getByRole('alert')).toContainText('cancelled X authorization');
  await continueWithX(page, E2E_ACCOUNT);
  await expect(page).toHaveURL(consent);
  await expect(page.getByRole('heading', { name: /Connect Browser smoke app/ })).toBeVisible();
  await expect(page.getByText('Signed in as', { exact: false })).toContainText('e2e@e2e-user.dev');
  await page.route(`${redirect}**`, (route) =>
    route.fulfill({ contentType: 'text/html', body: '<h1>App connected</h1>' }),
  );
  await page.getByRole('button', { name: 'Allow', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'App connected' })).toBeVisible();
  const returned = new URL(page.url());
  expect(returned.searchParams.get('state')).toBe('browser-smoke');
  expect(returned.searchParams.has('code')).toBe(true);
  await page.goto('/settings');
  await expect(
    page.getByRole('listitem', { name: 'Browser smoke app', exact: true }).last(),
  ).toBeVisible();
});

test('Profile keeps name edits and only the same X account can restore lost publishing access', async ({
  page,
}) => {
  runSeedScript('seed_user.py');
  await signIn(page);
  await expect(page).toHaveURL(/\/new$/);
  await page.goto('/settings');
  const original = await profile(page);
  const handle = page.getByRole('textbox', { name: 'X handle' });
  const email = page.getByRole('textbox', { name: 'Confirmed email' });
  await expect(handle).toHaveValue('@e2e_user');
  await expect(handle).toHaveAttribute('readonly', '');
  await expect(email).toHaveAttribute('readonly', '');
  await expect(
    page.getByRole('button', { name: /Change photo|Remove photo|Disconnect X/ }),
  ).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'X account', exact: true })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'First name' }).fill('Chosen');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await continueWithX(page, E2E_ACCOUNT);
  await expect(page).toHaveURL(/\/new$/);
  await page.goto('/settings');
  await expect(page.getByRole('textbox', { name: 'First name' })).toHaveValue('Chosen');
  expect((await profile(page)).id).toBe(original.id);

  runSeedScript('lose_x_authorization.py');
  await page.reload();
  await page.getByRole('button', { name: 'Reconnect X', exact: true }).click();
  await page.getByRole('button', { name: 'Grace (grace@e2e-user.dev)', exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole('alert').filter({ hasText: 'same X account' })).toBeVisible();
  await expect(handle).toHaveValue('@e2e_user');
  expect((await profile(page)).id).toBe(original.id);
  await page.getByRole('button', { name: 'Reconnect X', exact: true }).click();
  await page.getByRole('button', { name: E2E_ACCOUNT, exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole('region', { name: 'Reconnect X', exact: true })).toHaveCount(0);
  await expect(
    page.getByRole('status').filter({ hasText: 'Reconnected @e2e_user.' }),
  ).toBeVisible();
  await page
    .getByRole('navigation', { name: 'Main' })
    .first()
    .getByRole('link', { name: 'New post', exact: true })
    .click();
  await expect(page).toHaveURL(/\/new$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(handle).toHaveValue('@e2e_user');
});

test('retired callbacks cannot start a session or expose another sign-in method', async ({
  page,
}) => {
  const token = runSeedScript('seed_user.py').match(/E2E_ACCESS_TOKEN=(\S+)/)?.[1];
  if (!token) throw new Error('The managed seed printed no session credential');
  for (const path of [
    '/oauth/google/callback',
    '/auth/magic-link/callback',
    '/login/magic-link/sent',
  ]) {
    await page.goto(
      `${path}#access_token=${encodeURIComponent(token)}&expires_at=2099-01-01T00:00:00Z`,
    );
    await expect(page.getByRole('button', { name: 'Continue with X' })).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('pumpkit:session'))).toBeNull();
    await expect(page.getByRole('button', { name: /Google|Send magic link/ })).toHaveCount(0);
  }
  expect((await (await page.request.get('/api/v1/instance')).json()).sign_in_methods).toEqual([
    'x',
  ]);
  expect((await page.request.get('/api/v1/login/google')).status()).toBe(404);
  expect(
    (
      await page.request.post('/api/v1/login/magic-link/request', {
        data: { email: 'e2e@e2e-user.dev' },
      })
    ).status(),
  ).toBe(404);
});
