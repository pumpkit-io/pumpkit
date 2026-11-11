import { createServer, type Server } from 'node:http';
import { test, expect } from '@playwright/test';
import { assertEmulatedTarget } from '../personal-safety';

test('refuses a personal server before browser setup or seeding', async () => {
  const hosts: string[] = [];
  const server = createServer((req, res) => {
    hosts.push(req.headers.host ?? '');
    res.setHeader('X-Pumpkit-Dev-Mode', 'personal');
    res.end('healthy');
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address();
    if (!address || typeof address === 'string') throw new Error('No listener');
    for (const host of ['127.0.0.1', 'fixture.localhost']) {
      await expect(assertEmulatedTarget(`http://${host}:${address.port}`)).rejects.toThrow(
        'personal',
      );
    }
    expect(hosts).toEqual([`127.0.0.1:${address.port}`, `fixture.localhost:${address.port}`]);
  } finally {
    await close(server);
  }
});

function close(server: Server): Promise<void> {
  return new Promise((resolve) => server.close(() => resolve()));
}
