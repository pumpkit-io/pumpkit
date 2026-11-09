import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

interface Recipient {
  token: string;
  code: string;
  email: string;
}
interface BillingState {
  subscribed: boolean;
  trial_days: number | null;
  subscription: { current_period_end: string; introductory_trial_end: string | null } | null;
  free_access: {
    months: number;
    starts_at: string;
    ends_at: string;
    queued_starts_at: string | null;
  } | null;
  pending_coupon_operation_id: string | null;
}
interface Usage {
  allowance: {
    trial: boolean;
    resets_at: string;
    generations: { used: number; limit: number };
  };
}

// These optional journeys run only against a deliberately enabled, isolated Emulator stack.
test.skip(process.env.E2E_COUPONS !== '1', 'Enable the coupon suite as e2e/README.md describes.');
test.use({ storageState: { cookies: [], origins: [] }, trace: 'off' });

let catalog: Promise<string> | null = null;
test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/billing/plans', async (route) => {
    // Preserve the real catalog while repeated React loads avoid the shared public-read limit.
    catalog ??= route.fetch().then(async (answer) => {
      expect(answer.status(), 'the local Emulator catalog should load').toBe(200);
      const body = await answer.text();
      expect(JSON.parse(body).coupons_enabled).toBe(true);
      return body;
    });
    await route.fulfill({ status: 200, contentType: 'application/json', body: await catalog });
  });
});

async function recipient(page: Page, scenario = 'new'): Promise<Recipient> {
  const out = runSeedScript('coupon_user.py', [scenario]);
  const value = out.match(/E2E_COUPON=(.+)/)?.[1];
  if (!value) throw new Error('Coupon seed returned no recipient.');
  const saved = JSON.parse(value) as Recipient;
  await page.addInitScript((token) => {
    localStorage.setItem(
      'pumpkit:session',
      JSON.stringify({ accessToken: token, expiresAt: '2099-01-01T00:00:00.000Z' }),
    );
    localStorage.setItem('pumpkit:analytics-consent', JSON.stringify('denied'));
  }, saved.token);
  return saved;
}

async function get<T>(page: Page, user: Recipient, resource: string): Promise<T> {
  const answer = await page.request.get(`/api/v1/${resource}`, {
    headers: { Authorization: `Bearer ${user.token}` },
  });
  expect(answer.status(), `${resource} should be available`).toBe(200);
  return answer.json() as Promise<T>;
}

async function open(page: Page, path: string): Promise<void> {
  const loading = page.waitForResponse((r) => r.url().endsWith('/api/v1/billing/plans'));
  await page.goto(path);
  expect((await loading).status()).toBe(200);
}

async function review(page: Page, user: Recipient, inSettings = false): Promise<void> {
  await page
    .getByRole('button', { name: inSettings ? 'Redeem coupon' : 'Have a coupon?', exact: true })
    .click();
  await page.getByRole('textbox', { name: 'Coupon code' }).fill(user.code);
  await page.getByRole('button', { name: 'Check code', exact: true }).click();
  const preview = page.getByRole('status', { name: 'Coupon preview' });
  await expect(preview).toBeVisible();
  await expect(preview.getByRole('checkbox')).toHaveCount(2);
  for (const box of await preview.getByRole('checkbox').all()) await box.check();
}

async function redeem(page: Page): Promise<void> {
  await page
    .getByRole('status', { name: 'Coupon preview' })
    .getByRole('button', { name: 'Redeem coupon', exact: true })
    .click();
  await expect(page.getByText('Coupon redeemed', { exact: true })).toBeVisible();
}

test('cardless redemption opens Onboarding, gives full Usage and returns to the Paywall at expiry', async ({
  page,
}) => {
  const user = await recipient(page);
  await open(page, '/subscribe');
  await review(page, user);
  await expect(page.getByRole('status', { name: 'Coupon preview' })).toContainText(
    'No automatic payment',
  );
  await redeem(page);
  const me = await get<BillingState>(page, user, 'billing/me');
  expect(me.subscription).toBeNull();
  expect(me.subscribed).toBe(true);
  expect(me.trial_days).toBeNull();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding$/);

  runSeedScript('coupon_user.py', ['finish', user.email]);
  await open(page, '/settings');
  const usage = page.getByRole('region', { name: 'Usage', exact: true });
  await expect(usage.getByText('500 generations left', { exact: true })).toBeVisible();
  await expect(usage.getByRole('button', { name: /Buy top-up/ })).toBeVisible();
  await expect(usage.getByRole('button', { name: 'Subscribe now' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Plan', exact: true })).toContainText(
    'No automatic payment',
  );
  const counts = await get<Usage>(page, user, 'usage');
  expect(counts.allowance.trial).toBe(false);
  expect(counts.allowance.generations).toMatchObject({ limit: 500, used: 0 });

  runSeedScript('coupon_user.py', ['expire', user.email]);
  await page.reload();
  await expect(page).toHaveURL(/\/subscribe$/);
  await expect(page.getByRole('heading', { name: 'Subscribe to keep writing' })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Start trial:/ })).toHaveCount(0);
});

for (const interval of ['month', 'year']) {
  test(`an interrupted ${interval} subscriber claim recovers one deferral and preserves paid Usage`, async ({
    page,
  }) => {
    const user = await recipient(page, `subscriber-${interval}`);
    await open(page, '/settings');
    const before = await get<BillingState>(page, user, 'billing/me');
    const usageBefore = await get<Usage>(page, user, 'usage');
    await review(page, user, true);
    const preview = page.getByRole('status', { name: 'Coupon preview' });
    await expect(preview).toContainText('Next payment:');
    await expect(preview).toContainText('Your remaining paid time and usage stay intact.');
    let writes = 0;
    await page.route('**/api/v1/billing/coupons/redemptions', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      writes += 1;
      const committed = await route.fetch();
      expect(committed.status()).toBe(200);
      await route.abort('failed');
    });
    await preview.getByRole('button', { name: 'Redeem coupon', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('not confirmed yet');
    await expect(page.getByRole('button', { name: 'Check redemption' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Arrange subscription' })).toHaveCount(0);
    await page.reload();
    await expect(page.getByText('Coupon redeemed', { exact: true })).toBeVisible();
    expect(writes).toBe(1);
    const after = await get<BillingState>(page, user, 'billing/me');
    const usageAfter = await get<Usage>(page, user, 'usage');
    expect(after.free_access?.queued_starts_at).toBe(before.subscription?.current_period_end);
    expect(after.subscription?.current_period_end).toBe(after.free_access?.ends_at);
    expect(after.pending_coupon_operation_id).toBeNull();
    expect(after.free_access?.months).toBe(1);
    expect(usageAfter.allowance.resets_at).toBe(usageBefore.allowance.resets_at);
    expect(usageAfter.allowance.generations).toEqual(usageBefore.allowance.generations);
    expect(usageAfter.allowance.trial).toBe(false);
    await expect(page.getByText(/Queued free access:/)).toBeVisible();
  });
}

test('a coupon-only recipient explicitly arranges future payment without losing free time', async ({
  page,
}) => {
  const user = await recipient(page);
  await open(page, '/subscribe');
  await review(page, user);
  await redeem(page);
  runSeedScript('coupon_user.py', ['finish', user.email]);
  await open(page, '/settings');
  const before = await get<BillingState>(page, user, 'billing/me');
  expect(before.subscription).toBeNull();
  const plan = page.getByRole('region', { name: 'Plan', exact: true });
  await expect(plan.getByText('No automatic payment', { exact: true })).toBeVisible();
  await plan.getByRole('button', { name: 'Arrange subscription', exact: true }).click();
  await plan.getByRole('button', { name: 'Review monthly plan', exact: true }).click();
  const futureReview = plan.getByRole('region', { name: 'Review future subscription' });
  await expect(futureReview).toContainText('No immediate payment.');
  await expect(futureReview).toContainText('renews automatically until cancelled');
  await expect(futureReview.getByRole('checkbox')).toHaveCount(3);
  for (const box of await futureReview.getByRole('checkbox').all()) await box.check();
  const appOrigin = new URL(page.url()).origin;
  await futureReview.getByRole('button', { name: 'Agree and continue to checkout' }).click();
  await page.waitForURL((url) => url.origin !== appOrigin);
  expect(new URL(page.url()).hostname.endsWith('.localhost')).toBe(true);
  await expect(
    page.getByRole('heading', { name: 'Save a card for your accepted future plan' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Save card', exact: true }).click();
  await expect(page).toHaveURL(/\/settings(?:\?.*)?$/);
  await expect(
    page.getByText('Subscription arranged. Your free access stays unchanged.'),
  ).toBeVisible();
  const after = await get<BillingState>(page, user, 'billing/me');
  expect(after.free_access?.ends_at).toBe(before.free_access?.ends_at);
  expect(after.subscription?.current_period_end).toBe(before.free_access?.ends_at);
  expect(after.subscription?.introductory_trial_end).toBeNull();
  expect(after.subscribed).toBe(true);
});
