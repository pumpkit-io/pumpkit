import { createServer, type Server } from 'node:http';
import { test, expect } from '@playwright/test';
import { createXCallbackRelay } from '../../frontend/localXCallbackRelay';

test.describe('localhost X callback transport', () => {
  let server: Server;
  let origin: string;
  let callback: string;

  test.beforeEach(async () => {
    let relay: ReturnType<typeof createXCallbackRelay>;
    server = createServer((req, res) =>
      relay(req, res, () => {
        if (req.url === '/bind') {
          res.setHeader(
            'Set-Cookie',
            'x_sign_in_browser=fixture-binding; HttpOnly; SameSite=Lax; Path=/',
          );
        }
        res.setHeader('Content-Type', 'text/html');
        res.end('<title>Local callback fixture</title>');
      }),
    );
    await new Promise<void>((resolve) => server.listen(0, resolve));
    const address = server.address();
    if (!address || typeof address === 'string') throw new Error('No listener');
    origin = `http://localhost:${address.port}`;
    callback = `http://127.0.0.1:${address.port}/oauth/x/callback`;
    relay = createXCallbackRelay(origin);
  });

  test.afterEach(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  for (const purpose of ['signin', 'reconnect']) {
    test(`${purpose} returns to the original localhost cookie and storage`, async ({
      page,
      context,
    }) => {
      await page.goto(`${origin}/bind`);
      await page.evaluate(() => sessionStorage.setItem('return-to', '/settings'));
      expect(await context.cookies(callback)).toEqual([]);
      await page.goto(`${callback}?code=fixture-code&state=${purpose}.bound`);
      expect(page.url()).toBe(
        `${origin}/oauth/x/callback?code=fixture-code&state=${purpose}.bound`,
      );
      expect(
        (await context.cookies(origin)).find((cookie) => cookie.name === 'x_sign_in_browser')
          ?.value,
      ).toBe('fixture-binding');
      expect(await page.evaluate(() => sessionStorage.getItem('return-to'))).toBe('/settings');
      const response = await page.request.get(`${origin}/api/v1/health`);
      expect(response.headers()['x-pumpkit-dev-mode']).toBe('personal');
    });
  }

  test('cancellation returns to localhost without inventing browser credentials', async ({
    page,
    context,
  }) => {
    await page.goto(`${callback}?state=signin.bound&error=access_denied`);
    expect(page.url()).toBe(`${origin}/oauth/x/callback?state=signin.bound&error=access_denied`);
    expect(await context.cookies(origin)).toEqual([]);
  });
});
