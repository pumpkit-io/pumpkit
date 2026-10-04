import { act, renderHook, waitFor } from '@testing-library/react';
import { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/posthog', () => ({
  identifyUser: vi.fn(),
  resetPostHog: vi.fn(),
  capturePageview: vi.fn(),
  posthog: { capture: vi.fn(), register: vi.fn() },
}));

import { hardRedirect } from '@/lib/navigation';
import { resetPostHog } from '@/lib/posthog';
import { session } from '@/lib/session';
import { api } from '@/services/apiService';
import { AuthProvider, useAuth } from './AuthContext';

const SESSION_KEY = 'pumpkit:session';
const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>;
const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();
const originalAdapter = api.defaults.adapter;

const storeSession = (accessToken: string, expiresAt: string) =>
  localStorage.setItem(SESSION_KEY, JSON.stringify({ accessToken, expiresAt }));

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
            data: { email: 'a@example.com', first_name: null, last_name: null },
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
    storeSession('t', inMinutes(60));
    const backend = fakeBackend({ '/refresh-token': refreshed });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(backend.calls('/refresh-token')).toBe(0);
  });

  it('refreshes a near-expiry Session on boot', async () => {
    storeSession('t', inMinutes(5));
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
    storeSession('t', inMinutes(-5));
    fakeBackend({ '/refresh-token': answer });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(true);
    expect(session.get()?.accessToken).toBe('t');
    expect(hardRedirect).not.toHaveBeenCalled();
  });

  it('ends the Session when refresh is answered 401', async () => {
    storeSession('t', inMinutes(5));
    fakeBackend({ '/refresh-token': { status: 401, data: { detail: 'invalid_refresh_token' } } });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });
});

describe('AuthProvider while running', () => {
  it('refreshes a near-expiry Session when the window regains focus', async () => {
    storeSession('t', inMinutes(60));
    const backend = fakeBackend({ '/refresh-token': refreshed });
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    storeSession('t', inMinutes(5));
    act(() => {
      window.dispatchEvent(new Event('focus'));
    });

    await waitFor(() => expect(backend.calls('/refresh-token')).toBe(1));
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('signs out when another tab clears the Session', async () => {
    storeSession('t', inMinutes(60));
    fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    act(() => {
      const oldValue = localStorage.getItem(SESSION_KEY);
      localStorage.removeItem(SESSION_KEY);
      window.dispatchEvent(
        new StorageEvent('storage', { key: SESSION_KEY, oldValue, storageArea: localStorage }),
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
      localStorage.setItem(SESSION_KEY, newValue);
      window.dispatchEvent(
        new StorageEvent('storage', { key: SESSION_KEY, newValue, storageArea: localStorage }),
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
    storeSession('t', inMinutes(60));
    const backend = fakeBackend();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    await act(() => result.current.logout());

    expect(result.current.isAuthenticated).toBe(false);
    expect(backend.calls('/logout')).toBe(1);
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });
});
