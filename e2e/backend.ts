import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import * as path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '..');
// Written by `scripts/dev-stack up`: its Dev URL, then the Compose project serving it.
const DEV_STACK_TARGET_FILE = path.join(REPO_ROOT, '.sdlc', 'dev-stack', 'e2e-target');

/** Points seed scripts at the worktree's own stack when the suite runs against its Dev URL. */
function composeProjectArgs(): string[] {
  if (!existsSync(DEV_STACK_TARGET_FILE)) return [];
  const [devUrl, project] = readFileSync(DEV_STACK_TARGET_FILE, 'utf8').split('\n');
  return sameOrigin(process.env.E2E_BASE_URL, devUrl) ? ['-p', project] : [];
}

function sameOrigin(url: string | undefined, other: string): boolean {
  if (!url) return false;
  try {
    return new URL(url).origin === new URL(other).origin;
  } catch {
    return false;
  }
}

/** Runs one of `seed/`'s Python scripts inside the dev stack's backend container. */
export function runSeedScript(name: string): string {
  return execFileSync(
    'docker',
    [
      'compose',
      ...composeProjectArgs(),
      '-f',
      'compose.dev.yml',
      'exec',
      '-T',
      'backend',
      'python',
      '-',
    ],
    {
      cwd: REPO_ROOT,
      input: readFileSync(path.join(__dirname, 'seed', name), 'utf8'),
      encoding: 'utf8',
    },
  );
}
