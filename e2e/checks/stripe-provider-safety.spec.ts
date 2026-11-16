import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const script = path.resolve(__dirname, '../stripe-payment-method.mjs');
for (const [name, input] of [
  [
    'live session',
    JSON.stringify({
      url: 'https://billing.stripe.com/p/session?secret=live_sentinel',
      livemode: false,
    }),
  ],
  [
    'live ledger',
    JSON.stringify({
      url: 'https://billing.stripe.com/p/session?secret=test_sentinel',
      livemode: true,
    }),
  ],
  [
    'wrong host',
    JSON.stringify({ url: 'https://example.com/p/session?secret=test_sentinel', livemode: false }),
  ],
  [
    'userinfo',
    JSON.stringify({
      url: 'https://sentinel@billing.stripe.com/p/session?secret=test_sentinel',
      livemode: false,
    }),
  ],
  [
    'wrong port',
    JSON.stringify({
      url: 'https://billing.stripe.com:8443/p/session?secret=test_sentinel',
      livemode: false,
    }),
  ],
  ['malformed JSON', '{sentinel'],
  ['malformed URL', JSON.stringify({ url: 'sentinel', livemode: false })],
]) {
  test(`card verification refuses ${name} without exposing private input`, () => {
    const directory = mkdtempSync(path.join(tmpdir(), 'pumpkit-card-safety-'));
    const ledger = path.join(directory, 'private.json');
    try {
      writeFileSync(ledger, input, { mode: 0o600 });
      let result;
      try {
        execFileSync('node', [script, ledger, 'generic'], { encoding: 'utf8', stdio: 'pipe' });
      } catch (error) {
        result = error as { status: number; stderr: string };
      }
      expect(result?.status).toBe(2);
      expect(String(result?.stderr)).toContain('An owned Stripe test portal');
      expect(String(result?.stderr)).not.toContain('sentinel');
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
