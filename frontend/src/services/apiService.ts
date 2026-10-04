import axios, { AxiosResponse } from 'axios';
import { APP_SLUG } from '@/lib/app';
import { readSession, writeSession } from '@/lib/session/store';

// Create a shared axios instance with token refresh functionality
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// =============================================================================
// Refresh-token coordination
//
// The backend implements refresh-token rotation with theft detection: two
// parallel /refresh-token calls using the same cookie value will cause the
// second to be flagged as token replay and revoke the whole Session.
// To make refresh correct regardless of timing/frequency/tab count, we serialize
// refresh attempts on three levels:
//
//   1. In-flight promise dedup (this module): collapses repeat callers in the
//      SAME tab to a single network request.
//   2. Cross-tab Web Lock (`navigator.locks`): serializes refreshes across all
//      tabs of the same origin. Only one tab refreshes at a time.
//   3. Inside the lock, re-check whether refresh is still needed. The token
//      stored when performRefresh was first called is remembered; if by the
//      time we hold the lock the stored token is different (and still fresh
//      for 30s), another tab just refreshed, so we use it and skip the network
//      call. A token that is merely unexpired is NOT proof of a refresh, so
//      proactive and post-401 refreshes still reach /refresh-token.
//
// The Session module (`@/lib/session`) delegates every refresh (bootstrap,
// periodic, focus and the 401 interceptor) to performRefresh — there is
// exactly one path to /refresh-token.
// =============================================================================

const REFRESH_LOCK_NAME = `${APP_SLUG}:refresh-token`;

let refreshInFlight: Promise<string> | null = null;

async function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks =
    (typeof navigator !== 'undefined' &&
      (navigator as Navigator & { locks?: LockManager }).locks) ||
    null;
  if (locks) {
    return await locks.request(REFRESH_LOCK_NAME, async () => fn());
  }
  return fn();
}

function tokenStillFreshFor(seconds: number): boolean {
  const session = readSession();
  if (!session) return false;
  return new Date(session.expiresAt).getTime() > Date.now() + seconds * 1000;
}

export function performRefresh(): Promise<string> {
  if (refreshInFlight) return refreshInFlight;
  const observed = readSession()?.accessToken ?? null;
  refreshInFlight = withRefreshLock(async () => {
    // Another tab may have refreshed while we were waiting. If so, skip the
    // network call — the cookie has already been rotated and storage has the
    // new access token.
    const stored = readSession()?.accessToken ?? null;
    if (stored && stored !== observed && tokenStillFreshFor(30)) {
      return stored;
    }
    const response = await api.post('/refresh-token');
    const { access_token, expires_at } = response.data;
    writeSession({ accessToken: access_token, expiresAt: expires_at });
    return access_token;
  }).finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

// Add the access token to requests if there is a Session. The 401 → refresh →
// retry response interceptor lives in the Session module (`@/lib/session`),
// which owns the sign-out rule; `main.tsx` installs it with
// `installRefreshOnUnauthorized()`.
api.interceptors.request.use(
  (config) => {
    const session = readSession();
    if (session) {
      config.headers.Authorization = `Bearer ${session.accessToken}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  },
);

// Export the configured axios instance
export { api };

// Export a convenient service object
export const apiService = {
  get: <T = any>(url: string, config?: any): Promise<AxiosResponse<T>> => api.get(url, config),
  post: <T = any>(url: string, data?: any, config?: any): Promise<AxiosResponse<T>> =>
    api.post(url, data, config),
  put: <T = any>(url: string, data?: any, config?: any): Promise<AxiosResponse<T>> =>
    api.put(url, data, config),
  patch: <T = any>(url: string, data?: any, config?: any): Promise<AxiosResponse<T>> =>
    api.patch(url, data, config),
  delete: <T = any>(url: string, config?: any): Promise<AxiosResponse<T>> =>
    api.delete(url, config),
};
