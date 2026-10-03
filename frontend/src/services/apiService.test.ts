import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn() }));

import { hardRedirect } from '@/lib/navigation';
import { api, performRefresh } from './apiService';

const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();
const originalAdapter = api.defaults.adapter;

function adapter(statusByUrl: Record<string, number | 'network'>): AxiosAdapter {
  return async (config: InternalAxiosRequestConfig) => {
    const outcome = statusByUrl[config.url ?? ''] ?? 200;
    if (outcome === 'network') {
      throw new AxiosError('Network Error', 'ERR_NETWORK', config);
    }
    if (outcome >= 400) {
      throw new AxiosError('fail', String(outcome), config, null, {
        status: outcome,
        statusText: '',
        data: {},
        headers: {},
        config,
      });
    }
    const data =
      config.url === '/refresh-token' ? { access_token: 'refreshed', expires_at: inMinutes(30) } : { ok: true };
    return { data, status: 200, statusText: 'OK', headers: {}, config };
  };
}

describe('performRefresh', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('collapses concurrent calls into one request', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: { access_token: 'new', expires_at: inMinutes(30) },
    } as never);
    const [a, b] = await Promise.all([performRefresh(), performRefresh()]);
    expect([a, b]).toEqual(['new', 'new']);
    expect(post).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('auth_token')).toBe('new');
  });

  it('skips the network call when another tab refreshed while waiting for the lock', async () => {
    localStorage.setItem('auth_token', 'old');
    localStorage.setItem('token_expires_at', inMinutes(5));
    vi.stubGlobal('navigator', {
      ...navigator,
      locks: {
        request: vi.fn(async (_name: string, cb: () => Promise<unknown>) => {
          localStorage.setItem('auth_token', 'from-other-tab');
          localStorage.setItem('token_expires_at', inMinutes(30));
          return cb();
        }),
      },
    });
    const post = vi.spyOn(api, 'post');
    await expect(performRefresh()).resolves.toBe('from-other-tab');
    expect(post).not.toHaveBeenCalled();
  });

  it('refreshes over the network when the token is valid but nobody else refreshed', async () => {
    localStorage.setItem('auth_token', 'old');
    localStorage.setItem('token_expires_at', inMinutes(5));
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: { access_token: 'new', expires_at: inMinutes(30) },
    } as never);
    await expect(performRefresh()).resolves.toBe('new');
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('serializes through the app-scoped navigator lock', async () => {
    const request = vi.fn((_name: string, cb: () => Promise<unknown>) => cb());
    vi.stubGlobal('navigator', { ...navigator, locks: { request } });
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { access_token: 'new', expires_at: inMinutes(30) },
    } as never);
    await performRefresh();
    expect(request.mock.calls[0][0]).toBe('pumpkit:refresh-token');
  });
});

describe('401 interceptor', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(hardRedirect).mockClear();
    localStorage.setItem('auth_token', 'old');
    localStorage.setItem('token_expires_at', inMinutes(5));
  });
  afterEach(() => {
    api.defaults.adapter = originalAdapter;
  });

  it('retries the request with the refreshed token', async () => {
    let calls = 0;
    const base = adapter({});
    api.defaults.adapter = async (config) => {
      if (config.url === '/users/me' && calls++ === 0) return adapter({ '/users/me': 401 })(config);
      return base(config);
    };
    const response = await api.get('/users/me');
    expect(response.data).toEqual({ ok: true });
    expect(localStorage.getItem('auth_token')).toBe('refreshed');
  });

  it('signs out when /refresh-token returns 401', async () => {
    api.defaults.adapter = adapter({ '/users/me': 401, '/refresh-token': 401 });
    await expect(api.get('/users/me')).rejects.toBeTruthy();
    expect(localStorage.getItem('auth_token')).toBeNull();
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });

  it('keeps the session when refresh fails for a network error', async () => {
    api.defaults.adapter = adapter({ '/users/me': 401, '/refresh-token': 'network' });
    await expect(api.get('/users/me')).rejects.toBeTruthy();
    expect(localStorage.getItem('auth_token')).toBe('old');
    expect(hardRedirect).not.toHaveBeenCalled();
  });
});
