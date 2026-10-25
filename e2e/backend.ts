import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import * as path from 'node:path';

const REPO_ROOT = path.resolve(__dirname, '..');

/** Runs one of `seed/`'s Python scripts inside the dev stack's backend container. */
export function runSeedScript(name: string): string {
  return execFileSync(
    'docker',
    ['compose', '-f', 'compose.dev.yml', 'exec', '-T', 'backend', 'python', '-'],
    {
      cwd: REPO_ROOT,
      input: readFileSync(path.join(__dirname, 'seed', name), 'utf8'),
      encoding: 'utf8',
    },
  );
}
