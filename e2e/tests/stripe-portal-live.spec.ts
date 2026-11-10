import { execFile } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { expect, test, type Page, type Response } from '@playwright/test';

type Action = 'update' | 'cancel';
type Fixture = (command: string, options?: string[]) => Promise<Record<string, unknown>>;
interface Portal {
  session_url: string;
  login_url: string;
}

const root = path.resolve(__dirname, '../..');
const run = promisify(execFile);
const cancelAction = /Cancel (subscription|plan)/i;
const unsafeAction = new RegExp(
  `Subscribe and pay|${cancelAction.source}|(?:Update|Renew|Resume) (?:subscription|plan)`,
  'i',
);
test.skip(
  !process.env.PUMPKIT_STRIPE_TEST_KEY,
  'Requires an explicit Stripe test-mode credential.',
);

function mutation(answer: Response, action: Action): boolean {
  const endpoint = new URL(answer.url());
  return (
    answer.request().method() === 'POST' &&
    ['api.stripe.com', 'billing.stripe.com'].includes(endpoint.hostname) &&
    endpoint.pathname.includes('/billing_portal/sessions/') &&
    (action === 'cancel'
      ? /\/subscriptions\/[^/]+\/cancel$/.test(endpoint.pathname)
      : /\/subscriptions\/[^/]+$/.test(endpoint.pathname))
  );
}

async function withFixture(
  page: Page,
  mode: string,
  action: Action,
  behavior: string,
  exercise: (fixture: Fixture, portal: Portal, directory: string) => Promise<void>,
) {
  const directory = mkdtempSync(path.join(tmpdir(), 'pumpkit-portal-verification-'));
  const ledger = path.join(directory, 'private-resources.json');
  const fixture: Fixture = async (command, options = []) => {
    const { stdout } = await run(
      'uv',
      [
        'run',
        '--project',
        path.join(root, 'backend'),
        'python',
        path.join(root, 'backend/tests/billing/stripe_portal_fixture.py'),
        command,
        '--ledger',
        ledger,
        ...options,
      ],
      { encoding: 'utf8', timeout: 60_000 },
    );
    return JSON.parse(stdout) as Record<string, unknown>;
  };
  try {
    await fixture('create', ['--mode', mode, '--behavior', behavior, '--action', action]);
    const portal = JSON.parse(readFileSync(ledger, 'utf8')) as Portal;
    await page.goto(portal.session_url, { waitUntil: 'domcontentloaded' });
    if (action === 'update') {
      await expect(page.getByText(/What you.*pay yearly starting/)).toBeVisible();
    }
    await expect(page.getByText('Loading', { exact: true })).toBeHidden();
    await expect(confirmation(page, action)).toBeEnabled();
    await page.screenshot({ path: path.join(directory, 'before.png'), fullPage: true });
    await exercise(fixture, portal, directory);
  } catch (error) {
    writeFileSync(
      path.join(directory, 'private-error.txt'),
      String(error).replace(/https?:\/\/\S+/g, '[redacted URL]'),
      { mode: 0o600 },
    );
    throw new Error(`Portal verification failed; private evidence: ${directory}`);
  } finally {
    if (existsSync(ledger)) {
      await fixture('cleanup');
      rmSync(ledger);
    }
  }
}

function confirmation(page: Page, action: Action) {
  return page.getByRole('button', {
    name: action === 'update' ? /Subscribe and pay/ : cancelAction,
  });
}

async function rejection(answer: Response, transition: string) {
  const payload = (await answer.json()) as {
    error?: { code?: string; message?: string; type?: string; param?: string };
  };
  const error = payload.error ?? {};
  const message = error.message ?? '';
  const expected =
    transition === 'inactive-config'
      ? answer.status() === 400 && /config.*(?:inactive|disabled|not.*active)/i.test(message)
      : answer.status() === 404 &&
        error.code === 'resource_missing' &&
        /subscription/i.test(message);
  if (!expected) {
    const reason = {
      status: answer.status(),
      code: error.code,
      type: error.type,
      param: error.param,
    };
    throw new Error(`Unexpected provider refusal class: ${JSON.stringify(reason)}`);
  }
  return { status: answer.status(), code: error.code ?? null, kind: transition };
}

for (const mode of ['classic', 'flexible']) {
  for (const action of ['update', 'cancel'] as const) {
    for (const behavior of action === 'cancel' ? ['end_trial'] : ['end_trial', 'continue_trial']) {
      test(`control: unrestricted ${action}, ${mode}, ${behavior}`, async ({ page }) => {
        await withFixture(page, mode, action, behavior, async (fixture, _portal, directory) => {
          const response = page.waitForResponse((answer) => mutation(answer, action));
          await confirmation(page, action).click();
          expect((await response).status()).toBe(200);
          const observed = await fixture('observe');
          writeFileSync(
            path.join(directory, 'result.json'),
            JSON.stringify({ control: true, observed }),
          );
          if (action === 'cancel') {
            expect(observed).toMatchObject({
              status: 'trialing',
              price_preserved: true,
              trial_end_preserved: true,
              cancellation_preserved: false,
              cancellation_targets_original_end: true,
              nonzero_invoices: 0,
            });
          } else {
            expect(observed.price_preserved).toBe(false);
            expect(observed.status).toBe(behavior === 'end_trial' ? 'active' : 'trialing');
            expect(observed.trial_end_preserved).toBe(behavior === 'continue_trial');
            expect(observed.nonzero_invoices).toBe(behavior === 'end_trial' ? 1 : 0);
          }
        });
      });

      for (const transition of ['inactive-config', 'ended-legacy']) {
        test(`${transition}: stale ${action}, ${mode}, ${behavior}`, async ({ page }) => {
          await withFixture(page, mode, action, behavior, async (fixture, portal, directory) => {
            await fixture('restrict', transition === 'ended-legacy' ? ['--keep-active'] : []);
            if (transition === 'ended-legacy') await fixture('end-legacy');
            const refusals = [];
            for (let attempt = 0; attempt < 2; attempt++) {
              const response = page.waitForResponse((answer) => mutation(answer, action));
              await confirmation(page, action).click();
              refusals.push(await rejection(await response, transition));
              await expect(page.getByText(/Something went wrong/)).toBeVisible();
            }
            const observed = await fixture('observe');
            writeFileSync(
              path.join(directory, 'result.json'),
              JSON.stringify({ mode, transition, action, behavior, refusals, observed }, null, 2),
            );
            expect(observed).toMatchObject({
              status: transition === 'ended-legacy' ? 'canceled' : 'trialing',
              price_preserved: true,
              trial_end_preserved: true,
              cancellation_preserved: true,
              nonzero_invoices: 0,
            });
            if (transition === 'ended-legacy') expect(observed.replacement_preserved).toBe(true);
            await page.screenshot({ path: path.join(directory, 'after.png'), fullPage: true });
            await page.reload({ waitUntil: 'domcontentloaded' });
            await expect(
              page
                .getByText(
                  /Payment method|Invoice history|Billing history|Something went wrong|no longer|session.*expired/i,
                )
                .first(),
            ).toBeVisible();
            await expect(page.getByText('Loading', { exact: true })).toBeHidden();
            await expect(page.getByRole('button', { name: unsafeAction })).toHaveCount(0);
            await expect(page.getByRole('link', { name: unsafeAction })).toHaveCount(0);
            const login = await page.context().newPage();
            await login.goto(portal.login_url, { waitUntil: 'domcontentloaded' });
            await expect(login.getByText(/no longer active/)).toBeVisible();
          });
        });
      }
    }
  }
}
