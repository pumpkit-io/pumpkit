import { act, renderHook, waitFor } from '@testing-library/react';
import { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('posthog-js', () => {
  const posthog = {
    __loaded: false,
    init: vi.fn(() => {
      posthog.__loaded = true;
    }),
    opt_in_capturing: vi.fn(),
    // Records whether PostHog was initialised at the moment of each identification.
    identify: vi.fn(() => posthog.__loaded),
    register: vi.fn(),
    capture: vi.fn(),
    reset: vi.fn(),
  };
  return { default: posthog };
});
vi.mock('@/lib/analyticsConsent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analyticsConsent')>()),
  resetPostHog: vi.fn(),
}));

import { hardRedirect } from '@/lib/navigation';
import posthog from 'posthog-js';
import { grantAnalyticsConsent, resetPostHog, startAnalytics } from '@/lib/analyticsConsent';
import { SESSION_STORAGE_KEY, session } from '@/lib/session';
import { api } from '@/services/apiService';
import { AuthProvider, useAuth } from './AuthContext';

const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>;
const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();
const originalAdapter = api.defaults.adapter;
const ANALYTICS = {
  key: 'phc_test',
  host: 'https://eu.i.posthog.com',
  ui_host: 'https://eu.posthog.com',
};

type Answer = { status: number; data?: unknown } | 'network';

/** Fakes HTTP at the axios adapter. /users/me answers a profile by default. */
function fakeBackend(answers: Record<string, Answer> = {}) {
  const sent: string[] = [];
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const url = config.url ?? '';
    sent.push(url);
    const fallback: Answer =
      url === '/users/me'
        ? {
            status: 200,
            data: {
              id: 'user_01HZX',
              email: 'a@example.com',
              first_name: 'Ada',
              last_name: null,
              avatar_data_url: null,
            },
          }
        : { status: 200, data: {} };
    const answer = answers[url] ?? fallback;
    if (answer === 'network') throw new AxiosError('Network Error', 'ERR_NETWORK', config);
    const response = {
      data: answer.data ?? {},
      status: answer.status,
      statusText: '',
      headers: {},
      config,
    };
    if (answer.status >= 400)
      throw new AxiosError('fail', String(answer.status), config, null, response);
    return response;
  };
  return { calls: (url: string) => sent.filter((u) => u === url).length };
}

const refreshed = {
  status: 200,
  data: { access_token: 'new', token_type: 'Bearer', expires_at: inMinutes(30) },
};

beforeEach(async () => {
  await session.end('other_tab');
  localStorage.clear();
  sessionStorage.clear();
  vi.mocked(hardRedirect).mockClear();
  vi.mocked(resetPostHog).mockClear();
  vi.mocked(posthog.identify).mockClear();
  vi.mocked(posthog.init).mockClear();
  (posthog as unknown as { __loaded: boolean }).__loaded = false;
  startAnalytics(ANALYTICS);
});
afterEach(() => {
  api.defaults.adapter = originalAdapter;
});

describe('AuthProvider bootstrap', () => {
  it('is unauthenticated without a Session, with no network call and no redirect', async () => {
    const backend = fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(backend.calls('/refresh-token')).toBe(0);
    expect(hardRedirect).not.toHaveBeenCalled();
  });

  it('trusts a fresh Session without refreshing', async () => {
    session.start('t', inMinutes(60));
    const backend = fakeBackend({ '/refresh-token': refreshed });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(backend.calls('/refresh-token')).toBe(0);
  });

  it('refreshes a near-expiry Session on boot', async () => {
    session.start('t', inMinutes(5));
    const backend = fakeBackend({ '/refresh-token': refreshed });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(backend.calls('/refresh-token')).toBe(1);
    expect(session.get()?.accessToken).toBe('new');
  });

  it.each([
    ['a 503', { status: 503 } as Answer],
    ['a network error', 'network' as Answer],
  ])('stays signed in past expiry when refresh fails with %s', async (_label, answer) => {
    session.start('t', inMinutes(-5));
    fakeBackend({ '/refresh-token': answer });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(true);
    expect(session.get()?.accessToken).toBe('t');
    expect(hardRedirect).not.toHaveBeenCalled();
  });

  it('ends the Session when refresh is answered 401', async () => {
    session.start('t', inMinutes(5));
    fakeBackend({ '/refresh-token': { status: 401, data: { detail: 'invalid_refresh_token' } } });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });
});

describe('AuthProvider analytics identity', () => {
  it('never identifies a signed-in User without Analytics consent', async () => {
    session.start('t', inMinutes(60));
    const backend = fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    expect(backend.calls('/users/me')).toBe(0);
    expect(posthog.identify).not.toHaveBeenCalled();
  });

  it('identifies the person once by User ID after PostHog starts with stored consent', async () => {
    localStorage.setItem('pumpkit:analytics-consent', '"granted"');
    startAnalytics(ANALYTICS);
    session.start('t', inMinutes(60));
    fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    await waitFor(() => expect(posthog.identify).toHaveBeenCalled());
    expect(posthog.identify).toHaveBeenCalledTimes(1);
    expect(posthog.identify).toHaveBeenCalledWith('user_01HZX', {
      email: 'a@example.com',
      first_name: 'Ada',
      last_name: null,
    });
    expect(vi.mocked(posthog.identify).mock.results[0].value).toBe(true);
  });

  it('identifies a signed-in User once they accept analytics', async () => {
    session.start('t', inMinutes(60));
    fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(posthog.identify).not.toHaveBeenCalled();

    act(() => grantAnalyticsConsent());

    await waitFor(() => expect(posthog.identify).toHaveBeenCalledTimes(1));
    expect(vi.mocked(posthog.identify).mock.results[0].value).toBe(true);
  });
});

describe('AuthProvider while running', () => {
  it('refreshes a near-expiry Session when the window regains focus', async () => {
    session.start('t', inMinutes(60));
    const backend = fakeBackend({ '/refresh-token': refreshed });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    session.start('t', inMinutes(5));
    act(() => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(() => expect(backend.calls('/refresh-token')).toBe(1));
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('signs out when another tab clears the Session', async () => {
    session.start('t', inMinutes(60));
    fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    act(() => {
      const oldValue = localStorage.getItem(SESSION_STORAGE_KEY);
      localStorage.removeItem(SESSION_STORAGE_KEY);
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: SESSION_STORAGE_KEY,
          oldValue,
          storageArea: localStorage,
        }),
      );
    });

    await waitFor(() => expect(result.current.isAuthenticated).toBe(false));
    expect(resetPostHog).toHaveBeenCalledTimes(1);
  });

  it('signs in when another tab starts a Session', async () => {
    fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      const newValue = JSON.stringify({ accessToken: 't', expiresAt: inMinutes(60) });
      localStorage.setItem(SESSION_STORAGE_KEY, newValue);
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: SESSION_STORAGE_KEY,
          newValue,
          storageArea: localStorage,
        }),
      );
    });

    expect(result.current.isAuthenticated).toBe(true);
  });

  it('becomes authenticated when a sign-in callback starts a Session in this tab', async () => {
    fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const expiresAt = inMinutes(60);
    act(() => {
      session.startFromFragment(`#access_token=t&expires_at=${encodeURIComponent(expiresAt)}`);
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(session.get()).toEqual({ accessToken: 't', expiresAt });
  });

  it('logout ends the Session with the backend and routes to the sign-in page', async () => {
    session.start('t', inMinutes(60));
    const backend = fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    await act(() => result.current.logout());

    expect(result.current.isAuthenticated).toBe(false);
    expect(backend.calls('/logout')).toBe(1);
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });
});
