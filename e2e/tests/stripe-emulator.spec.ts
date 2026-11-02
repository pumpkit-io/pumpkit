import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

// A User of its own per test, so each one starts at the Paywall.
test.use({ storageState: { cookies: [], origins: [] } });

async function signInAsNewUser(page: Page): Promise<void> {
  const email = `e2e-subscriber-${Date.now()}@e2e-user.dev`;
  const token = runSeedScript('new_user.py', [email]).match(/E2E_ACCESS_TOKEN=(\S+)/)?.[1];
  if (!token) throw new Error('new_user.py printed no token');
  await page.addInitScript((t) => {
    localStorage.setItem(
      'pumpkit:session',
      JSON.stringify({ accessToken: t, expiresAt: '2099-01-01T00:00:00.000Z' }),
    );
    localStorage.setItem('pumpkit:analytics-consent', JSON.stringify('denied'));
  }, token);
}

const planButtons = (page: Page) => page.getByRole('button', { name: /^Start trial: / });

/** Opens the Paywall once it lists Plans. */
async function openPaywall(page: Page): Promise<void> {
  await page.goto('/subscribe');
  // The suite's earlier specs share one client address, which can use up /billing/plans'
  // per-minute limit: reload until the window lets the Paywall load its Plans.
  await expect(async () => {
    if (await page.getByText("Couldn't load plans.").isVisible()) await page.reload();
    await expect(planButtons(page)).toHaveCount(2, { timeout: 2_000 });
  }).toPass({ timeout: 70_000 });
}

/** Opens Checkout for the monthly Plan, or skips when Checkout is Stripe's own. */
async function startMonthlyTrial(page: Page): Promise<void> {
  await openPaywall(page);
  for (const box of await page.getByRole('checkbox').all()) await box.check();
  const appOrigin = new URL(page.url()).origin;
  await page.getByRole('button', { name: /^Start trial: .*month/i }).click();
  await page.waitForURL((url) => url.origin !== appOrigin);
  test.skip(
    new URL(page.url()).hostname.endsWith('stripe.com'),
    'Checkout is Stripe itself: run the suite against scripts/dev-stack.',
  );
}

test('the Paywall offers the Plans the Stripe Emulator sells', async ({ page }) => {
  await signInAsNewUser(page);

  await openPaywall(page);

  await expect(page.getByRole('button', { name: /^Start trial: .*month/i })).toHaveCount(1);
  await expect(page.getByRole('button', { name: /^Start trial: .*year/i })).toHaveCount(1);
});

test('a Trial bought through the Emulator Checkout opens Onboarding', async ({ page }) => {
  await signInAsNewUser(page);
  await startMonthlyTrial(page);
  const emulator = new URL(page.url()).origin;

  await page.getByRole('button', { name: 'Pay' }).click();

  await expect(page).toHaveURL(/\/onboarding$/);
  // Every webhook the Checkout sent was accepted, so the backend learnt of the Trial from them.
  const deliveries = await (
    await page.request.get(`${emulator}/_pumpkit/webhook-deliveries`)
  ).json();
  expect(deliveries.map((d: { event: string }) => d.event)).toEqual(
    expect.arrayContaining(['customer.subscription.created', 'checkout.session.completed']),
  );
  expect(deliveries.filter((d: { status_code: number }) => d.status_code !== 200)).toEqual([]);
});
