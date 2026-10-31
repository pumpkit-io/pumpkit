import { expect, test, type Page } from '@playwright/test';
import { runSeedScript } from '../backend';

test.use({ storageState: { cookies: [], origins: [] } });

async function seedUsage(page: Page, scenario: 'paid' | 'limit' | 'trial' = 'paid') {
  const out = runSeedScript('usage_user.py', [scenario]);
  const match = out.match(/E2E_USAGE=(.+)/);
  if (!match) throw new Error('Usage seed did not return a session');
  const { token, postId } = JSON.parse(match[1]) as { token: string; postId: string };
  await page.addInitScript((accessToken) => {
    localStorage.setItem(
      'pumpkit:session',
      JSON.stringify({ accessToken, expiresAt: '2099-01-01T00:00:00.000Z' }),
    );
    localStorage.setItem('pumpkit:analytics-consent', JSON.stringify('denied'));
  }, token);
  return postId;
}

test.beforeEach(async ({ page }) => {
  // The catalog reads Stripe; Subscription and usage responses still come from the dev backend.
  await page.route('**/api/v1/billing/plans', (route) =>
    route.fulfill({
      json: {
        data: [
          {
            key: 'pumpkit_pro_monthly',
            product_name: 'Pro',
            amount: 1900,
            currency: 'eur',
            interval: 'month',
            interval_count: 1,
          },
        ],
        terms_version: null,
        allowance: { generations: 500, x_posts: 100, link_x_posts: 10 },
        trial: { days: 7, generations: 125, x_posts: 25, link_x_posts: 2 },
        top_up: { amount: 1000, currency: 'eur', generations: 250, x_posts: 50, link_x_posts: 5 },
      },
    }),
  );
});

test('Settings shows remaining usage directly below the Plan card', async ({ page }) => {
  await seedUsage(page);
  await page.goto('/settings');
  const plan = page.getByRole('region', { name: 'Plan', exact: true });
  const usage = page.getByRole('region', { name: 'Usage', exact: true });
  await expect(usage.getByText('497 generations left', { exact: true })).toBeVisible();
  await expect(usage.getByText('99 X posts left, 9 of them with a link')).toBeVisible();
  await expect(usage.getByText(/^Resets on the \d+(st|nd|rd|th) of each month/)).toBeVisible();
  await expect(usage.getByRole('meter', { name: 'Generations left' })).toHaveAttribute(
    'aria-valuenow',
    '497',
  );
  await expect(usage.getByRole('meter', { name: 'X posts left' })).toHaveAttribute(
    'aria-valuenow',
    '99',
  );
  const planBox = await plan.boundingBox();
  const usageBox = await usage.boundingBox();
  expect(planBox).not.toBeNull();
  expect(usageBox).not.toBeNull();
  expect(usageBox!.y).toBeGreaterThanOrEqual(planBox!.y + planBox!.height);
});

test('New post shows the generations limit instead of an error banner', async ({ page }) => {
  await seedUsage(page, 'limit');
  await page.goto('/new');
  await page.getByLabel('Brief', { exact: true }).fill('A post that exceeds my allowance.');
  const response = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/posts') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Write the post' }).click();
  expect((await response).status()).toBe(409);
  const notice = page.getByRole('status').filter({ hasText: /generations/ });
  await expect(notice).toContainText(/used.*500.*generations/i);
  await expect(notice.getByRole('button', { name: /Buy top-up/ })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page).toHaveURL(/\/new$/);
});

test('Post to explains the link post it will use', async ({ page }) => {
  const postId = await seedUsage(page);
  await page.goto(`/posts/${postId}`);
  await page.getByRole('button', { name: 'Post to…', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Contains a link: uses 1 of your 9 link posts')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});

for (const scenario of ['paid', 'trial'] as const) {
  test(`${scenario === 'paid' ? 'Buy top-up' : 'Subscribe now'} opens and cancels without payment`, async ({
    page,
  }) => {
    const paymentRequests: string[] = [];
    await page.route('**/api/v1/billing/**', async (route) => {
      if (route.request().method() === 'POST') {
        paymentRequests.push(route.request().url());
        await route.abort();
      } else {
        await route.fallback();
      }
    });
    await seedUsage(page, scenario);
    await page.goto('/settings');
    const usage = page.getByRole('region', { name: 'Usage' });
    await usage
      .getByRole('button', { name: scenario === 'paid' ? /Buy top-up/ : 'Subscribe now' })
      .click();
    const dialog = page.getByRole('dialog', {
      name: scenario === 'paid' ? 'Buy a top-up' : 'Subscribe now',
    });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(
      scenario === 'paid'
        ? '250 generations and 50 X posts, up to 5 with a link'
        : 'Your monthly allowance of 500 generations and 100 X posts starts at once.',
    );
    await expect(
      dialog.getByRole('button', { name: scenario === 'paid' ? /Pay €10/ : 'Subscribe now' }),
    ).toBeEnabled();
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(/\/settings$/);
    expect(paymentRequests).toEqual([]);
  });
}
