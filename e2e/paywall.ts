import { expect, type Page } from './fixtures';

export const MONTHLY = /^(Start trial|Subscribe): .*month/i;

export async function openPaywall(page: Page): Promise<void> {
  // The Paywall's Plans are rate limited per client, so reload until they list.
  await expect(async () => {
    await page.goto('/subscribe');
    await expect(page.getByRole('button', { name: MONTHLY })).toBeVisible({ timeout: 5_000 });
  }).toPass({ timeout: 70_000 });
}

export interface Delivery {
  event: string;
  object: string;
  customer: string | null;
}

export async function deliveries(page: Page, stripe: string): Promise<Delivery[]> {
  return (await page.request.get(`${stripe}/_pumpkit/webhook-deliveries`)).json();
}

/** Subscribes through the Stripe Emulator's Checkout, which ends on Onboarding; answers with its origin and the customer. */
export async function subscribe(page: Page): Promise<{ stripe: string; customer: string }> {
  await openPaywall(page);
  for (const box of await page.getByRole('checkbox').all()) await box.check();
  await page.getByRole('button', { name: MONTHLY }).click();
  const pay = page.getByRole('button', { name: 'Pay' });
  await expect(pay).toBeVisible();
  const checkout = new URL(page.url());
  const sessionId = checkout.pathname.split('/').pop() ?? '';
  await pay.click();
  await expect(page).toHaveURL(/\/onboarding$/);
  const customer = (await deliveries(page, checkout.origin)).find(
    (d) => d.object === sessionId,
  )?.customer;
  if (!customer) throw new Error('The Emulator delivered no event for the Checkout');
  return { stripe: checkout.origin, customer };
}
