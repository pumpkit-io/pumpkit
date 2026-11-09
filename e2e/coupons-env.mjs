import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
if (
  git('rev-parse', '--absolute-git-dir') ===
  git('rev-parse', '--path-format=absolute', '--git-common-dir')
) {
  throw new Error('Prepare coupon tests in an isolated linked worktree.');
}
const env = path.join(root, '.env');
const directory = path.join(root, '.sdlc', 'dev-stack');
const backup = path.join(directory, 'coupons-env-backup');
if (process.argv[2] === 'restore') {
  if (!existsSync(backup)) throw new Error('No saved environment to restore.');
  writeFileSync(env, readFileSync(backup), { mode: 0o600 });
  console.log('Restored this worktree’s environment. Restart through scripts/dev-stack.');
} else if (process.argv[2] === 'prepare') {
  const original = readFileSync(env, 'utf8');
  mkdirSync(directory, { recursive: true });
  if (!existsSync(backup)) writeFileSync(backup, original, { mode: 0o600 });
  const values = {
    COUPONS_ENABLED: 'true',
    OPERATOR_NAME: "'Pumpkit E2E'",
    SUPPORT_EMAIL: 'support@e2e-user.dev',
    STRIPE_COUPON_PORTAL_CONFIGURATION_ID: 'bpc_coupon_management',
    COUPON_IDENTITY_KEYS: `'${JSON.stringify({ active: 'e2e', keys: { e2e: Buffer.alloc(32, 42).toString('base64') } })}'`,
  };
  let updated = original;
  for (const [key, value] of Object.entries(values)) {
    const line = new RegExp(`^${key}=.*$`, 'm');
    updated = line.test(updated)
      ? updated.replace(line, `${key}=${value}`)
      : `${updated.trimEnd()}\n${key}=${value}\n`;
  }
  writeFileSync(env, updated, { mode: 0o600 });
  console.log('Prepared local coupon configuration. Start only through scripts/dev-stack.');
} else {
  throw new Error('Use: node e2e/coupons-env.mjs prepare|restore');
}
