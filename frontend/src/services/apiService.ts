import axios, { AxiosResponse } from 'axios';
import { APP_SLUG } from '@/lib/app';
import { hardRedirect } from '@/lib/navigation';

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
// Both the response interceptor (on 401) and authService.refreshToken delegate
// to performRefresh — there is exactly one path to /refresh-token.
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

function readStoredToken(): { token: string | null; expiresAt: string | null } {
  return {
    token: localStorage.getItem('auth_token'),
    expiresAt: localStorage.getItem('token_expires_at'),
  };
}

function tokenStillFreshFor(seconds: number): boolean {
  const { token, expiresAt } = readStoredToken();
  if (!token || !expiresAt) return false;
  return new Date(expiresAt).getTime() > Date.now() + seconds * 1000;
}

export function performRefresh(): Promise<string> {
  if (refreshInFlight) return refreshInFlight;
  const observed = localStorage.getItem('auth_token');
  refreshInFlight = withRefreshLock(async () => {
    // Another tab may have refreshed while we were waiting. If so, skip the
    // network call — the cookie has already been rotated and our localStorage
    // has the new access token.
    const stored = readStoredToken().token;
    if (stored && stored !== observed && tokenStillFreshFor(30)) {
      return stored;
    }
    const response = await api.post('/refresh-token');
    const { access_token, expires_at } = response.data;
    localStorage.setItem('auth_token', access_token);
    localStorage.setItem('token_expires_at', expires_at);
    return access_token;
  }).finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

// =============================================================================
// 401 retry queue: serializes other in-flight requests that 401'd while a
// refresh is happening, so they retry with the new token after refresh.
// =============================================================================

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: any) => void;
  reject: (error: any) => void;
}> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error);
    } else {
      resolve(token);
    }
  });
  failedQueue = [];
};

// Add auth token to requests if available
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  },
);

// Add response interceptor with automatic token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const requestUrl = originalRequest?.url ?? '';

    // Skip retry/refresh logic for auth endpoints that expect 401s
    if (['/login', '/refresh-token'].some((path) => requestUrl?.includes(path))) {
      return Promise.reject(error);
    }

    // If error is 401 and we haven't already tried to refresh
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return api(originalRequest);
          })
          .catch((err) => {
            return Promise.reject(err);
          });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const newToken = await performRefresh();
        processQueue(null, newToken);

        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return api(originalRequest);
      } catch (refreshError: any) {
        processQueue(refreshError, null);

        // A 401 from /refresh-token is unambiguous: the session is dead and
        // no retry will fix it. Clear local auth state and bounce to /login.
        // For non-401 failures (network, 5xx) we keep the session in place —
        // the still-valid access token can be used until it actually expires.
        const refreshStatus = refreshError?.response?.status;
        const expiresAt = localStorage.getItem('token_expires_at');
        const accessTokenLooksExpired = !!expiresAt && new Date(expiresAt).getTime() <= Date.now();
        const accessTokenMissing = !localStorage.getItem('auth_token');
        const mustSignOut = refreshStatus === 401 || accessTokenMissing || accessTokenLooksExpired;

        if (mustSignOut) {
          localStorage.removeItem('auth_token');
          localStorage.removeItem('token_expires_at');
          hardRedirect('/login');
        }
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

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
