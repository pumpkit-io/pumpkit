import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

// A User of its own per test, so each one starts at the Paywall.
test.use({ storageState: { cookies: [], origins: [] } });

async function signInAsNewUser(page: Page): Promise<string> {
  const email = `e2e-newcomer-${Date.now()}@e2e-user.dev`;
  const token = runSeedScript('new_user.py', [email]).match(/E2E_ACCESS_TOKEN=(\S+)/)?.[1];
  if (!token) throw new Error('new_user.py printed no token');
  await page.addInitScript((t) => {
    localStorage.setItem(
      'pumpkit:session',
      JSON.stringify({ accessToken: t, expiresAt: '2099-01-01T00:00:00.000Z' }),
    );
    localStorage.setItem('pumpkit:analytics-consent', JSON.stringify('denied'));
  }, token);
  return token;
}

interface Delivery {
  event: string;
  status_code: number | null;
  object: string;
  customer: string;
}

const planButtons = (page: Page) => page.getByRole('button', { name: /^Start trial: / });

/** Opens the Paywall once it lists Plans, or skips when the stack's Stripe can't list them. */
async function openPaywall(page: Page): Promise<void> {
  let status = 0;
  // The suite's earlier specs share one client address, which can use up /billing/plans'
  // per-minute limit: reload until the window lets the Paywall load its Plans.
  await expect(async () => {
    const plans = page.waitForResponse((r) => r.url().endsWith('/api/v1/billing/plans'));
    await page.goto('/subscribe');
    status = (await plans).status();
    expect(status).not.toBe(429);
  }).toPass({ timeout: 70_000 });
  test.skip(
    status !== 200,
    `Plans answered ${status}: run the suite against scripts/dev-stack's Stripe Emulator.`,
  );
  await expect(planButtons(page)).toHaveCount(2);
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
  const checkout = new URL(page.url());
  const sessionId = checkout.pathname.split('/').pop();

  await page.getByRole('button', { name: 'Pay' }).click();

  await expect(page).toHaveURL(/\/onboarding$/);
  // This User's webhooks were all accepted, so the backend learnt of the Trial from them.
  const all: Delivery[] = await (
    await page.request.get(`${checkout.origin}/_pumpkit/webhook-deliveries`)
  ).json();
  const customer = all.find((d) => d.object === sessionId)?.customer;
  const mine = all.filter((d) => d.customer === customer);
  expect(mine.map((d) => [d.event, d.status_code])).toEqual([
    ['customer.created', 200],
    ['customer.subscription.created', 200],
    ['checkout.session.completed', 200],
  ]);
});

test('a Top-up bought through the Emulator Checkout reaches the backend', async ({ page }) => {
  const token = await signInAsNewUser(page);
  await startMonthlyTrial(page);
  await page.getByRole('button', { name: 'Pay' }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  const headers = { Authorization: `Bearer ${token}` };
  // Top-ups are for paid Subscriptions, so the Trial ends first.
  const subscribed = await page.request.post('/api/v1/billing/subscribe-now', { headers });
  expect(subscribed.status()).toBe(200);
  const { terms_version } = await (await page.request.get('/api/v1/billing/plans')).json();
  const acceptance = terms_version
    ? {
        terms_version,
        accepted_terms: true,
        requested_immediate_start: true,
        approved_specific_clauses: true,
      }
    : {};

  const checkout = await page.request.post('/api/v1/billing/top-ups/checkout', {
    headers,
    data: acceptance,
  });
  expect(checkout.status()).toBe(200);
  const { url, session_id: sessionId } = await checkout.json();
  await page.goto(url);
  await page.getByRole('button', { name: 'Pay' }).click();

  // The Emulator delivers its webhooks before sending the browser back to Pumpkit.
  await page.waitForURL((u) => u.origin !== new URL(url).origin);
  const all: Delivery[] = await (
    await page.request.get(`${new URL(url).origin}/_pumpkit/webhook-deliveries`)
  ).json();
  expect(all.filter((d) => d.object === sessionId).map((d) => [d.event, d.status_code])).toEqual([
    ['checkout.session.completed', 200],
  ]);
});
