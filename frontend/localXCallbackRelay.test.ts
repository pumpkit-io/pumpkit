import { createServer, request as httpRequest, type Server } from 'node:http';
import { afterEach, describe, expect, it } from 'vitest';
import { createXCallbackRelay } from './localXCallbackRelay';

let server: Server;
afterEach(async () => {
  if (server) await new Promise<void>((resolve) => server.close(() => resolve()));
});

async function request(
  host: string,
  path: string,
  method = 'GET',
  publicURL = 'http://localhost:5173',
) {
  const relay = createXCallbackRelay(publicURL);
  server = createServer((req, res) => relay(req, res, () => res.end('app')));
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('No listener');
  return new Promise<Response>((resolve, reject) => {
    const req = httpRequest(
      { hostname: '127.0.0.1', port: address.port, path, method, headers: { Host: host } },
      (res) => {
        let body = '';
        res.on('data', (chunk) => {
          body += chunk;
        });
        res.on('end', () =>
          resolve(
            new Response(body, {
              status: res.statusCode,
              headers: res.headers as Record<string, string>,
            }),
          ),
        );
      },
    );
    req.on('error', reject);
    req.end();
  });
}

describe('local X callback relay', () => {
  it('returns X credentials to the fixed localhost callback before serving the app', async () => {
    const res = await request(
      '127.0.0.1:5173',
      '/oauth/x/callback?code=a%2Bb&state=signin.bound&return_to=https://evil.example&access_token=secret',
    );
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(
      'http://localhost:5173/oauth/x/callback?code=a%2Bb&state=signin.bound',
    );
    expect(res.headers.get('cache-control')).toBe('no-store');
    expect(res.headers.get('referrer-policy')).toBe('no-referrer');
  });
  it('accepts the browser-normalized Host for the default HTTP port', async () => {
    const res = await request(
      '127.0.0.1',
      '/oauth/x/callback?state=signin.bound&code=valid',
      'GET',
      'http://localhost:80',
    );
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toBe(
      'http://localhost/oauth/x/callback?state=signin.bound&code=valid',
    );
  });
  it('relays cancellation for the existing callback handler', async () => {
    const res = await request(
      '127.0.0.1:5173',
      '/oauth/x/callback?state=reconnect.bound&error=access_denied',
    );
    expect(res.headers.get('location')).toBe(
      'http://localhost:5173/oauth/x/callback?state=reconnect.bound&error=access_denied',
    );
  });
  it.each([
    ['localhost:5173', '/oauth/x/callback', 'GET'],
    ['evil.example:5173', '/oauth/x/callback', 'GET'],
    ['127.0.0.1:5174', '/oauth/x/callback', 'GET'],
    ['127.0.0.1:5173', '/oauth/x/callback/extra', 'GET'],
    ['127.0.0.1:5173', '/oauth/x/callback', 'POST'],
  ])('does not relay %s %s %s', async (host, path, method) => {
    const res = await request(host, path, method);
    expect(res.headers.get('X-Pumpkit-Dev-Mode')).toBe('personal');
    expect(res.status).toBe(200);
    expect(await res.text()).toBe('app');
  });
  it.each([
    'https://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost',
    'http://localhost:5173/path',
  ])('rejects an invalid destination %s', (url) => {
    expect(() => createXCallbackRelay(url)).toThrow('localhost');
  });
});
