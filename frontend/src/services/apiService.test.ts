import type { InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, performRefresh } from './apiService';

const SESSION_KEY = 'pumpkit:session';
const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();
const originalAdapter = api.defaults.adapter;

const storedSession = () => JSON.parse(localStorage.getItem(SESSION_KEY) ?? 'null');
const storeSession = (accessToken: string, expiresAt: string) =>
  localStorage.setItem(SESSION_KEY, JSON.stringify({ accessToken, expiresAt }));

/** Fakes HTTP at the axios adapter; /refresh-token answers with `token`. */
function fakeRefresh(token: string) {
  const sent: string[] = [];
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    sent.push(config.url ?? '');
    await new Promise((r) => setTimeout(r, 0));
    const data = { access_token: token, token_type: 'Bearer', expires_at: inMinutes(30) };
    return { data, status: 200, statusText: 'OK', headers: {}, config };
  };
  return { refreshCalls: () => sent.filter((url) => url === '/refresh-token').length };
}

describe('performRefresh', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    api.defaults.adapter = originalAdapter;
    vi.unstubAllGlobals();
  });

  it('collapses concurrent calls into one request and stores the new Session', async () => {
    const backend = fakeRefresh('new');
    const [a, b] = await Promise.all([performRefresh(), performRefresh()]);
    expect([a, b]).toEqual(['new', 'new']);
    expect(backend.refreshCalls()).toBe(1);
    expect(storedSession()).toEqual({ accessToken: 'new', expiresAt: expect.any(String) });
  });

  it('skips the network call when another tab refreshed while waiting for the lock', async () => {
    storeSession('old', inMinutes(5));
    vi.stubGlobal('navigator', {
      ...navigator,
      locks: {
        request: async (_name: string, cb: () => Promise<unknown>) => {
          storeSession('from-other-tab', inMinutes(30));
          return cb();
        },
      },
    });
    const backend = fakeRefresh('new');
    await expect(performRefresh()).resolves.toBe('from-other-tab');
    expect(backend.refreshCalls()).toBe(0);
  });

  it('refreshes over the network when the token is valid but nobody else refreshed', async () => {
    storeSession('old', inMinutes(5));
    const backend = fakeRefresh('new');
    await expect(performRefresh()).resolves.toBe('new');
    expect(backend.refreshCalls()).toBe(1);
  });

  it('serializes through the app-scoped navigator lock', async () => {
    const lockNames: string[] = [];
    vi.stubGlobal('navigator', {
      ...navigator,
      locks: {
        request: (name: string, cb: () => Promise<unknown>) => {
          lockNames.push(name);
          return cb();
        },
      },
    });
    fakeRefresh('new');
    await performRefresh();
    expect(lockNames).toEqual(['pumpkit:refresh-token']);
  });
});

describe('request interceptor', () => {
  afterEach(() => {
    api.defaults.adapter = originalAdapter;
  });

  it('sends the Session access token as a bearer token', async () => {
    storeSession('t', inMinutes(30));
    let authorization: unknown;
    api.defaults.adapter = async (config) => {
      authorization = config.headers?.Authorization;
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
    };
    await api.get('/users/me');
    expect(authorization).toBe('Bearer t');
  });
});
