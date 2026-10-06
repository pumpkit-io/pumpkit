import axios, { AxiosResponse } from 'axios';
import { APP_SLUG } from '@/lib/app';
import { readSession, writeSession } from '@/lib/session/store';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Refresh-token rotation revokes the Session when two calls reuse one cookie, so refreshes are
// deduped within a tab and serialized across tabs; every refresh goes through performRefresh.

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
    // Another tab may have rotated the cookie while we waited. A merely unexpired token is not
    // proof of that, so only a changed token counts.
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

// The 401 → refresh → retry interceptor lives in `@/lib/session`, installed from `main.tsx`.
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

export { api };

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
