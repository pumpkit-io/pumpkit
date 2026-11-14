// Completes a Stripe test-mode hosted Checkout with Stripe's published Visa test card.
// Used by backend/tests/billing/test_stripe_managed_payments_live.py.
import { chromium } from 'playwright';

const [url] = process.argv.slice(2);
if (!url?.startsWith('https://checkout.stripe.com/c/pay/cs_test_')) {
  console.error('usage: node stripe-checkout.mjs <test-mode Checkout URL>');
  process.exit(2);
}
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'networkidle' });
  // Payment-mode Checkouts list payment methods to choose from; subscription mode shows the card form.
  const card = page.locator('#cardNumber');
  if (!(await card.isVisible())) {
    // The accordion's cover takes the pointer, so the click goes straight to the button.
    await page.getByTestId('card-accordion-item-button').dispatchEvent('click');
  }
  await card.pressSequentially('4242424242424242', { delay: 30 });
  await page.locator('#cardExpiry').pressSequentially('1234', { delay: 30 });
  await page.locator('#cardCvc').pressSequentially('123', { delay: 30 });
  await page.locator('#billingName').pressSequentially('Synthetic Tester', { delay: 20 });
  // Checkout validates the typed card in the background and exposes no signal for when it's done.
  await page.waitForTimeout(1500);
  // Stripe redirects to the success URL once the Checkout completes; that page needn't load.
  const redirected = page.waitForRequest(
    (request) =>
      request.isNavigationRequest() &&
      request.frame() === page.mainFrame() &&
      !request.url().startsWith('https://checkout.stripe.com/'),
    { timeout: 90_000 },
  );
  await page.locator('button[type=submit]').click();
  await redirected;
} finally {
  await browser.close();
}
