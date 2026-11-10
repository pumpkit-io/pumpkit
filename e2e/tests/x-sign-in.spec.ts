import { expect, test } from '@playwright/test';
import { stagedXBaseURL } from '../backend';

test.use({ storageState: { cookies: [], origins: [] } });

test('the prepared X flow completes browser and server calls without mounting production routes', async ({
  page,
}) => {
  const staged = stagedXBaseURL();
  test.skip(!staged, 'This protocol check needs scripts/dev-stack.');
  await page.goto(staged!);
  await page.getByRole('button', { name: 'Continue with X' }).click();
  await expect(page.getByRole('heading', { name: 'Authorize local X account' })).toBeVisible();
  await page.getByRole('button', { name: 'Ada (ada@e2e-user.dev)' }).click();
  await expect(page.getByRole('status')).toHaveText('Signed in');
  const first = JSON.parse((await page.locator('#profile').textContent())!);
  expect(first.email).toBe('ada@e2e-user.dev');
  expect(first.handle).toBe('ada');
  expect(first.name).toBe('Ada');
  expect(first.hasPhoto).toBe(true);
  expect(
    (await page.context().cookies()).find((cookie) => cookie.name.endsWith('refresh_token'))
      ?.httpOnly,
  ).toBe(true);
  await page.goto(staged!);
  await page.getByRole('button', { name: 'Continue with X' }).click();
  await page.getByRole('button', { name: 'Ada (ada@e2e-user.dev)' }).click();
  await expect(page.getByRole('status')).toHaveText('Signed in');
  expect(JSON.parse((await page.locator('#profile').textContent())!).id).toBe(first.id);
  const instance = await (await page.request.get('/api/v1/instance')).json();
  const main = await page.request.get('/api/v1/login/x');
  expect(main.status()).toBe(instance.sign_in_methods.includes('x') ? 200 : 404);
  if (!instance.sign_in_methods.includes('x')) {
    expect((await page.request.post('/api/v1/login/x/complete', { data: {} })).status()).toBe(404);
  }
});

test('missing confirmed email and cancellation produce no session', async ({ page }) => {
  const staged = stagedXBaseURL();
  test.skip(!staged, 'This protocol check needs scripts/dev-stack.');
  await page.goto(staged!);
  await page.getByRole('button', { name: 'Continue with X' }).click();
  await page.getByRole('button', { name: 'No email (no confirmed email)' }).click();
  await expect(page.getByRole('status')).toHaveText('x_email_required');
  expect(
    (await page.context().cookies()).some((cookie) => cookie.name.endsWith('refresh_token')),
  ).toBe(false);
  await page.getByRole('link', { name: 'Retry' }).click();
  await page.getByRole('button', { name: 'Continue with X' }).click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('x_authorization_cancelled');
});

test('the local provider consumes PKCE codes and rotates refresh credentials without publishing', async ({
  request,
}) => {
  const staged = stagedXBaseURL();
  test.skip(!staged, 'This protocol check needs scripts/dev-stack.');
  const started = await (await request.get(`${staged}/api/v1/login/x`)).json();
  const authorize = new URL(started.url);
  const endpoint = `${authorize.origin}/2/oauth2/token`;
  const headers = {
    Authorization: `Basic ${Buffer.from('pumpkit-dev-x:pumpkit-dev-x-secret').toString('base64')}`,
  };
  const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
  const form = Object.fromEntries(authorize.searchParams);
  form.code_challenge = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
  form.user_id = '1001';
  async function code() {
    const consent = await request.post(authorize.toString(), { form, maxRedirects: 0 });
    expect(consent.status()).toBe(303);
    const value = new URL(consent.headers().location).searchParams.get('code');
    if (!value) throw new Error('Local authorization returned no code');
    return value;
  }
  const rejected = await code();
  const exchange = (value: string, proof: string) =>
    request.post(endpoint, {
      headers,
      form: {
        grant_type: 'authorization_code',
        code: value,
        code_verifier: proof,
        redirect_uri: form.redirect_uri,
      },
    });
  expect((await exchange(rejected, 'wrong')).status()).toBe(400);
  expect((await exchange(rejected, verifier)).status()).toBe(400);
  const accepted = await exchange(await code(), verifier);
  expect(accepted.status()).toBe(200);
  const credentials = await accepted.json();
  const rotated = await request.post(endpoint, {
    headers,
    form: { grant_type: 'refresh_token', refresh_token: credentials.refresh_token },
  });
  expect(rotated.status()).toBe(200);
  expect(
    (
      await request.post(endpoint, {
        headers,
        form: { grant_type: 'refresh_token', refresh_token: credentials.refresh_token },
      })
    ).status(),
  ).toBe(400);
  const current = await rotated.json();
  const bearer = { Authorization: `Bearer ${current.access_token}` };
  const profile = await (
    await request.get(
      `${authorize.origin}/2/users/me?user.fields=name,confirmed_email,profile_image_url`,
      { headers: bearer },
    )
  ).json();
  expect(profile.data.confirmed_email).toBe('ada@e2e-user.dev');
  expect(profile.data.name).toBe('Ada');
  expect(typeof profile.data.profile_image_url).toBe('string');
  expect(
    (
      await request.post(`${authorize.origin}/2/tweets`, {
        headers: bearer,
        data: { text: 'Local only' },
      })
    ).status(),
  ).toBe(403);
  expect(
    (
      await request.post(`${authorize.origin}/2/media/upload/initialize`, {
        headers: bearer,
        data: {},
      })
    ).status(),
  ).toBe(403);
  const getProfile = (accessToken: string) =>
    request.get(`${authorize.origin}/2/users/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  const revoke = (value: string, hint: string) =>
    request.post(`${authorize.origin}/2/oauth2/revoke`, {
      headers,
      form: { token: value, token_type_hint: hint },
    });
  expect((await revoke(current.access_token, 'access_token')).status()).toBe(200);
  expect((await getProfile(current.access_token)).status()).toBe(401);
  expect((await getProfile(credentials.access_token)).status()).toBe(200);
  const nextRefresh = await request.post(endpoint, {
    headers,
    form: { grant_type: 'refresh_token', refresh_token: current.refresh_token },
  });
  expect(nextRefresh.status()).toBe(200);
  const next = await nextRefresh.json();
  const separate = await (await exchange(await code(), verifier)).json();
  expect((await getProfile(next.access_token)).status()).toBe(200);
  expect((await revoke(next.refresh_token, 'refresh_token')).status()).toBe(200);
  expect((await getProfile(credentials.access_token)).status()).toBe(401);
  expect((await getProfile(next.access_token)).status()).toBe(401);
  expect((await getProfile(separate.access_token)).status()).toBe(200);
  expect(
    (
      await request.post(endpoint, {
        headers,
        form: { grant_type: 'refresh_token', refresh_token: next.refresh_token },
      })
    ).status(),
  ).toBe(400);
  const events = await (await request.get(`${authorize.origin}/_pumpkit/events`)).json();
  expect(events.some((event: { kind: string }) => event.kind === 'profile')).toBe(true);
  for (const event of events) expect(Object.keys(event).sort()).toEqual(['kind', 'userId']);
});
