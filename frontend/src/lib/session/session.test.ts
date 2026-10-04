import { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/posthog', () => ({
  identifyUser: vi.fn(),
  resetPostHog: vi.fn(),
  capturePageview: vi.fn(),
  posthog: { capture: vi.fn(), register: vi.fn() },
}));

import { hardRedirect } from '@/lib/navigation';
import { resetPostHog } from '@/lib/posthog';
import { api } from '@/services/apiService';
import { session } from '@/lib/session';

const SESSION_KEY = 'pumpkit:session';
const IDENTIFIED_KEY = 'pumpkit:posthog-identified';
const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();
const originalAdapter = api.defaults.adapter;

type Answer =
  | { status: number; data?: unknown }
  | 'network'
  | ((config: InternalAxiosRequestConfig) => Answer | Promise<Answer>);

interface SentRequest {
  url: string;
  authorization: string | undefined;
}

/** Fakes HTTP at the axios adapter: records every request, answers per URL. */
function fakeBackend(answers: Record<string, Answer>) {
  const sent: SentRequest[] = [];
  api.defaults.adapter = async (config) => {
    const url = config.url ?? '';
    sent.push({ url, authorization: config.headers?.Authorization as string | undefined });
    let answer: Answer = answers[url] ?? { status: 200, data: { ok: true } };
    while (typeof answer === 'function') answer = await answer(config);
    if (answer === 'network') throw new AxiosError('Network Error', 'ERR_NETWORK', config);
    const response = {
      data: answer.data ?? {},
      status: answer.status,
      statusText: '',
      headers: {},
      config,
    };
    if (answer.status >= 400) {
      throw new AxiosError('fail', String(answer.status), config, null, response);
    }
    return response;
  };
  return { sent, calls: (url: string) => sent.filter((r) => r.url === url) };
}

const refreshed = (token: string) => ({
  status: 200,
  data: { access_token: token, token_type: 'Bearer', expires_at: inMinutes(30) },
});
const refused = { status: 401, data: { detail: 'invalid_refresh_token' } };

beforeEach(async () => {
  // Every test starts signed out in this tab.
  await session.end('other_tab');
  localStorage.clear();
  sessionStorage.clear();
  vi.mocked(hardRedirect).mockClear();
  vi.mocked(resetPostHog).mockClear();
});
afterEach(() => {
  api.defaults.adapter = originalAdapter;
});

describe('refresh', () => {
  it('ends the Session when the refresh is answered 401', async () => {
    session.start('old', inMinutes(5));
    sessionStorage.setItem(IDENTIFIED_KEY, '1');
    fakeBackend({ '/refresh-token': refused });

    await expect(session.refresh()).rejects.toBeTruthy();

    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(session.get()).toBeNull();
    expect(sessionStorage.getItem(IDENTIFIED_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });

  it('ends the Session with account_suspended when the refresh is answered 401 account_suspended', async () => {
    session.start('old', inMinutes(5));
    sessionStorage.setItem(IDENTIFIED_KEY, '1');
    fakeBackend({ '/refresh-token': { status: 401, data: { detail: 'account_suspended' } } });

    await expect(session.refresh()).rejects.toBeTruthy();

    expect(session.get()).toBeNull();
    expect(sessionStorage.getItem(IDENTIFIED_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login?error=account_suspended');
  });
});

describe('transient refresh failures', () => {
  it.each([
    ['a 503', { status: 503 } as Answer],
    ['a network error', 'network' as Answer],
  ])('keep the Session in place past expiry on %s', async (_label, answer) => {
    session.start('expired', inMinutes(-5));
    sessionStorage.setItem(IDENTIFIED_KEY, '1');
    fakeBackend({ '/refresh-token': answer });

    await expect(session.refresh()).rejects.toBeTruthy();

    expect(session.get()).toEqual({ accessToken: 'expired', expiresAt: expect.any(String) });
    expect(sessionStorage.getItem(IDENTIFIED_KEY)).toBe('1');
    expect(resetPostHog).not.toHaveBeenCalled();
    expect(hardRedirect).not.toHaveBeenCalled();
  });
});

describe('a protected request answered 401', () => {
  /** /users/me accepts only `Bearer <token>`; anything else is a 401. */
  const meAccepting =
    (token: string) =>
    (config: InternalAxiosRequestConfig): Answer =>
      config.headers?.Authorization === `Bearer ${token}`
        ? { status: 200, data: { email: 'a@example.com' } }
        : { status: 401, data: { detail: 'Could not validate credentials' } };

  it('refreshes, then retries with the new token', async () => {
    session.start('old', inMinutes(5));
    const backend = fakeBackend({
      '/users/me': meAccepting('new'),
      '/refresh-token': refreshed('new'),
    });

    const response = await api.get('/users/me');

    expect(response.data).toEqual({ email: 'a@example.com' });
    expect(backend.calls('/refresh-token')).toHaveLength(1);
    expect(backend.calls('/users/me').map((r) => r.authorization)).toEqual([
      'Bearer old',
      'Bearer new',
    ]);
    expect(session.get()?.accessToken).toBe('new');
  });

  it('causes exactly one refresh for several concurrent 401s', async () => {
    session.start('old', inMinutes(5));
    const backend = fakeBackend({
      '/users/me': meAccepting('new'),
      '/refresh-token': async () => {
        await new Promise((r) => setTimeout(r, 0));
        return refreshed('new');
      },
    });

    const responses = await Promise.all([
      api.get('/users/me'),
      api.get('/users/me'),
      api.get('/users/me'),
    ]);

    expect(responses.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(backend.calls('/refresh-token')).toHaveLength(1);
    const retries = backend.calls('/users/me').filter((r) => r.authorization === 'Bearer new');
    expect(retries).toHaveLength(3);
  });

  it('retries a late 401 with the current token instead of refreshing again', async () => {
    session.start('old', inMinutes(5));
    let first = true;
    const backend = fakeBackend({
      '/users/me': (config) => {
        if (first) {
          // The Session was refreshed while this request was in flight.
          first = false;
          session.start('new', inMinutes(30));
        }
        return meAccepting('new')(config);
      },
      '/refresh-token': refreshed('newer'),
    });

    const response = await api.get('/users/me');

    expect(response.status).toBe(200);
    expect(backend.calls('/refresh-token')).toHaveLength(0);
  });

  it('ends the Session with session_ended when the refresh is answered 401', async () => {
    session.start('old', inMinutes(5));
    fakeBackend({ '/users/me': meAccepting('new'), '/refresh-token': refused });

    await expect(api.get('/users/me')).rejects.toBeTruthy();

    expect(session.get()).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });

  it('keeps the Session when the refresh fails with a network error', async () => {
    session.start('old', inMinutes(-1));
    fakeBackend({ '/users/me': meAccepting('new'), '/refresh-token': 'network' });

    await expect(api.get('/users/me')).rejects.toBeTruthy();

    expect(session.get()?.accessToken).toBe('old');
    expect(hardRedirect).not.toHaveBeenCalled();
  });

  it('does not refresh without a Session', async () => {
    const backend = fakeBackend({ '/users/me': meAccepting('new') });

    await expect(api.get('/users/me')).rejects.toBeTruthy();

    expect(backend.calls('/refresh-token')).toHaveLength(0);
    expect(hardRedirect).not.toHaveBeenCalled();
  });
});

/** What this tab sees when another tab changes `key` in localStorage. */
function otherTabWrites(key: string | null, newValue: string | null) {
  const oldValue = key ? localStorage.getItem(key) : null;
  if (key === null) localStorage.clear();
  else if (newValue === null) localStorage.removeItem(key);
  else localStorage.setItem(key, newValue);
  window.dispatchEvent(
    new StorageEvent('storage', { key, oldValue, newValue, storageArea: localStorage }),
  );
}

describe('other tabs', () => {
  it('ends the Session here with other_tab when another tab clears it', async () => {
    session.start('t', inMinutes(60));
    sessionStorage.setItem(IDENTIFIED_KEY, '1');
    const seen: Array<unknown> = [];
    const unsubscribe = session.subscribe((s) => seen.push(s));
    const backend = fakeBackend({});

    otherTabWrites(SESSION_KEY, null);

    await vi.waitFor(() => expect(hardRedirect).toHaveBeenCalledWith('/login'));
    expect(seen).toEqual([null]);
    expect(sessionStorage.getItem(IDENTIFIED_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(backend.sent).toHaveLength(0);
    unsubscribe();
  });

  it('ends the Session here when another tab clears all of localStorage', async () => {
    session.start('t', inMinutes(60));

    otherTabWrites(null, null);

    await vi.waitFor(() => expect(hardRedirect).toHaveBeenCalledWith('/login'));
    expect(resetPostHog).toHaveBeenCalledTimes(1);
  });

  it('passes a Session started in another tab to subscribers', () => {
    const seen: Array<unknown> = [];
    const unsubscribe = session.subscribe((s) => seen.push(s));
    const started = { accessToken: 'from-other-tab', expiresAt: inMinutes(30) };

    otherTabWrites(SESSION_KEY, JSON.stringify(started));

    expect(seen).toEqual([started]);
    expect(session.get()).toEqual(started);
    expect(hardRedirect).not.toHaveBeenCalled();
    unsubscribe();
  });

  it('ignores storage events when this tab has no Session', async () => {
    otherTabWrites(null, null);
    otherTabWrites('pumpkit:theme', '"dark"');
    await new Promise((r) => setTimeout(r, 0));
    expect(hardRedirect).not.toHaveBeenCalled();
    expect(resetPostHog).not.toHaveBeenCalled();
  });
});

describe('signing out', () => {
  it('calls backend logout and ends the Session', async () => {
    session.start('t', inMinutes(60));
    const backend = fakeBackend({});

    await session.end('user');

    expect(backend.calls('/logout')).toHaveLength(1);
    expect(session.get()).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });

  it.each([
    ['answers 500', { status: 500 } as Answer],
    ['answers 401', { status: 401 } as Answer],
    ['is unreachable', 'network' as Answer],
  ])('ends the Session even when backend logout %s', async (_label, answer) => {
    session.start('t', inMinutes(60));
    sessionStorage.setItem(IDENTIFIED_KEY, '1');
    const backend = fakeBackend({ '/logout': answer });

    await session.end('user');

    expect(backend.calls('/refresh-token')).toHaveLength(0);
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
    expect(sessionStorage.getItem(IDENTIFIED_KEY)).toBeNull();
    expect(resetPostHog).toHaveBeenCalledTimes(1);
    expect(hardRedirect).toHaveBeenCalledWith('/login');
  });
});
