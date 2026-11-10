import { execFile } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';
import { expect, test } from '@playwright/test';

const root = path.resolve(__dirname, '../..');
const run = promisify(execFile);
const enabled = Boolean(process.env.PUMPKIT_STRIPE_TEST_KEY);
test.skip(!enabled, 'Requires an explicit Stripe test-mode credential.');

for (const mode of ['classic', 'flexible']) {
  for (const transition of ['inactive-config', 'ended-legacy']) {
    for (const action of ['update', 'cancel']) {
      for (const behavior of action === 'cancel'
        ? ['end_trial']
        : ['end_trial', 'continue_trial']) {
        test(`${transition}: stale ${action}, ${mode}, ${behavior}`, async ({ page }) => {
          const directory = mkdtempSync(path.join(tmpdir(), 'pumpkit-portal-verification-'));
          const ledger = path.join(directory, 'private-resources.json');
          const posts: { route: string; status: number }[] = [];
          page.on('response', (answer) => {
            if (
              answer.request().method() === 'POST' &&
              /^https:\/\/(api|billing)\.stripe\.com\//.test(answer.url())
            ) {
              const route = new URL(answer.url()).pathname
                .split('/')
                .map((part) => (/^[a-z_]{1,40}$/.test(part) ? part : ':id'))
                .join('/');
              posts.push({ route, status: answer.status() });
            }
          });
          const fixture = async (command: string, options: string[] = []) => {
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
            const data = JSON.parse(readFileSync(ledger, 'utf8')) as {
              session_url: string;
              login_url: string;
            };
            await page.goto(data.session_url, { waitUntil: 'domcontentloaded' });
            const confirm = page.getByRole('button', {
              name: action === 'update' ? /Subscribe and pay/ : /Cancel (subscription|plan)/i,
            });
            if (action === 'update') {
              await expect(page.getByText(/What you.*pay yearly starting/)).toBeVisible();
            }
            await expect(page.getByText('Loading', { exact: true })).toBeHidden();
            await expect(confirm).toBeEnabled();
            await page.screenshot({ path: path.join(directory, 'before.png'), fullPage: true });
            await fixture('restrict', transition === 'ended-legacy' ? ['--keep-active'] : []);
            if (transition === 'ended-legacy') await fixture('end-legacy');
            const statuses: number[] = [];
            for (let attempt = 0; attempt < 2; attempt++) {
              const response = page.waitForResponse(
                (answer) =>
                  answer.request().method() === 'POST' &&
                  /^https:\/\/(api|billing)\.stripe\.com\//.test(answer.url()) &&
                  new URL(answer.url()).pathname.includes('/billing_portal/sessions/') &&
                  new URL(answer.url()).pathname.includes('/subscriptions/') &&
                  (action !== 'cancel' || new URL(answer.url()).pathname.endsWith('/cancel')),
              );
              await confirm.click();
              statuses.push((await response).status());
              await expect(page.getByText(/Something went wrong/)).toBeVisible();
            }
            const observed = await fixture('observe');
            writeFileSync(
              path.join(directory, 'result.json'),
              JSON.stringify(
                { mode, transition, action, behavior, statuses, observed, posts },
                null,
                2,
              ),
            );
            expect(statuses.every((status) => status >= 400 && status < 500)).toBe(true);
            expect(observed).toMatchObject({
              status: transition === 'ended-legacy' ? 'canceled' : 'trialing',
              price_preserved: true,
              trial_end_preserved: true,
              cancellation_preserved: true,
              nonzero_invoices: 0,
            });
            if (transition === 'ended-legacy') expect(observed.replacement_preserved).toBe(true);
            const login = await page.context().newPage();
            await login.goto(data.login_url, { waitUntil: 'domcontentloaded' });
            await expect(login.getByText(/no longer active/)).toBeVisible();
            await page.screenshot({ path: path.join(directory, 'after.png'), fullPage: true });
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
        });
      }
    }
  }
}
