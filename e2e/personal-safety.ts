import { existsSync, readFileSync } from 'node:fs';
import * as path from 'node:path';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';

export function assertSeedStack(): void {
  const modeFile = path.resolve(__dirname, '../.sdlc/dev-stack/mode');
  if (existsSync(modeFile) && readFileSync(modeFile, 'utf8').trim() === 'personal') {
    throw new Error(
      'E2E seeds cannot run from a personal stack worktree. Use an emulated worktree.',
    );
  }
}

export async function assertEmulatedTarget(baseURL: string): Promise<void> {
  assertSeedStack();
  const url = new URL('/api/v1/health', baseURL);
  const host = url.host;
  const servername = url.hostname;
  // Portless names are loopback even where the OS resolver does not recognize *.localhost.
  if (url.hostname.endsWith('.localhost')) url.hostname = '127.0.0.1';
  const request = url.protocol === 'https:' ? httpsRequest : httpRequest;
  await new Promise<void>((resolve, reject) => {
    const req = request(url, { headers: { Host: host }, servername }, (response) => {
      response.resume();
      if (response.headers['x-pumpkit-dev-mode'] === 'personal') {
        reject(new Error('E2E cannot target the personal stack. Use an emulated stack.'));
      } else if (!response.statusCode || response.statusCode < 200 || response.statusCode >= 300) {
        reject(new Error('E2E target health check failed.'));
      } else {
        resolve();
      }
    });
    req.on('error', reject);
    req.setTimeout(10_000, () => req.destroy(new Error('E2E target health check timed out.')));
    req.end();
  });
}
