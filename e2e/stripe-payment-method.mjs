import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright';

const [ledger, action] = process.argv.slice(2);
let url;
try {
  const input = JSON.parse(readFileSync(ledger, 'utf8'));
  const target = new URL(input.url);
  if (
    target.protocol !== 'https:' ||
    target.hostname !== 'billing.stripe.com' ||
    target.port ||
    target.username ||
    target.password ||
    target.hash ||
    target.pathname !== '/p/session' ||
    !target.searchParams.get('secret')?.startsWith('test_') ||
    input.livemode !== false ||
    !['generic', 'existing', 'new', 'inspect'].includes(action)
  )
    throw new Error();
  url = input.url;
} catch {
  console.error('An owned Stripe test portal and a supported card operation are required');
  process.exit(2);
}
const browser = await chromium.launch({ headless: false });
let page;
try {
  page = await browser.newPage({ viewport: { width: 1280, height: 1600 } });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.getByText('Add payment method', { exact: true }).waitFor();
  const control = (name) => page.getByRole('button', { name }).or(page.getByRole('link', { name }));
  const subscriptionUpdate = control('Update payment method');
  if (action === 'inspect') {
    console.log(
      JSON.stringify({
        card_update: (await subscriptionUpdate.count()) > 0,
        cancel: (await control(/Cancel (subscription|plan)/i).count()) > 0,
        price_change:
          (await control(/(?:Update|Change|Switch) (?:subscription|plan)/i).count()) > 0,
      }),
    );
  } else {
    if (action !== 'generic') {
      await subscriptionUpdate.click();
      await page.getByText('Select a payment method', { exact: true }).waitFor();
    }
    if (action === 'existing') {
      await page.getByText(/Mastercard/).click();
      await page.getByRole('button', { name: /^(Update|Subscribe and pay)$/, exact: true }).click();
    } else {
      await page.getByText('Add payment method', { exact: true }).click();
      const payment = page.frameLocator('iframe[title="Secure payment input frame"]');
      await payment
        .locator('#payment-numberInput')
        .pressSequentially('5555555555554444', { delay: 30 });
      await payment.locator('#payment-expiryInput').pressSequentially('1234', { delay: 30 });
      await payment.locator('#payment-cvcInput').pressSequentially('123', { delay: 30 });
      await payment.getByLabel('Country', { exact: true }).selectOption('IT');
      await payment.locator('#payment-cvcInput').blur();
      await page.getByTestId('confirm').click();
    }
    if (action === 'generic') {
      await page.getByText('Default', { exact: true }).waitFor({ timeout: 60_000 });
    } else {
      await page
        .getByText('Select a payment method', { exact: true })
        .waitFor({ state: 'hidden', timeout: 60_000 });
      await page.getByText('Add payment method', { exact: true }).waitFor({ timeout: 60_000 });
    }
  }
} catch (error) {
  if (page && !page.isClosed()) {
    try {
      writeFileSync(
        `${ledger}.page.txt`,
        (await page.locator('body').innerText()).replace(/https?:\/\/\S+/g, '[redacted URL]'),
        { mode: 0o600 },
      );
      await page.screenshot({ path: `${ledger}.page.png`, fullPage: true });
    } catch {
      console.error('Private failure evidence could not be captured');
    }
  }
  console.error(
    String(error)
      .replace(/https?:\/\/\S+/g, '[redacted URL]')
      .replace(/\b(?:\d[ -]?){12,19}\b/g, '[redacted card]'),
  );
  process.exitCode = 1;
} finally {
  await browser.close();
}
