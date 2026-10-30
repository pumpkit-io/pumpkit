import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import * as path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '..');
// Written by `scripts/dev-stack up`, which runs this worktree's stack under a Compose project of its own.
const DEV_STACK_PROJECT_FILE = path.join(REPO_ROOT, '.sdlc', 'dev-stack', 'compose-project');

function composeProjectArgs(): string[] {
  if (!process.env.E2E_BASE_URL || !existsSync(DEV_STACK_PROJECT_FILE)) return [];
  return ['-p', readFileSync(DEV_STACK_PROJECT_FILE, 'utf8').trim()];
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
