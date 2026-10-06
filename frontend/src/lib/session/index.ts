import { isAxiosError, type InternalAxiosRequestConfig } from 'axios';
import { hardRedirect } from '@/lib/navigation';
import { resetPostHog } from '@/lib/posthog';
import { storageKey } from '@/lib/storage';
import { api, performRefresh } from '@/services/apiService';
import { SIGN_IN_ERROR, signInPath } from './signInError';
import {
  clearSession,
  readSession,
  SESSION_STORAGE_KEY,
  writeSession,
  type Session,
} from './store';

export type { Session } from './store';
export { SESSION_STORAGE_KEY } from './store';
export { SIGN_IN_ERROR, isSignInErrorCode, signInPath, type SignInErrorCode } from './signInError';

/**
 * Why a Session ended.
 * - `user`: the User signed out (also calls backend logout).
 * - `session_ended`: the refresh endpoint answered 401.
 * - `account_suspended`: the refresh endpoint answered 401 because the User is Suspended.
 * - `other_tab`: Session storage was cleared in another tab.
 */
export type EndSessionReason = 'user' | 'session_ended' | 'account_suspended' | 'other_tab';

/**
 * Why a sign-in callback's fragment could not start a Session; the callback page maps it to an error code.
 * - `missing_token`: no `access_token`.
 * - `invalid_expiry`: no `expires_at`, or one that is not a date.
 */
export type StartFailureReason = 'missing_token' | 'invalid_expiry';

export type StartFromFragmentResult = { ok: true } | { ok: false; reason: StartFailureReason };

/**
 * The sessionStorage key (per tab) marking that analytics already identified
 * the User in this Session. Ending a Session clears it.
 */
export const POSTHOG_IDENTIFIED_KEY = storageKey('posthog-identified');

const ROUTE_AFTER_END: Record<EndSessionReason, string> = {
  user: signInPath(),
  session_ended: signInPath(),
  account_suspended: signInPath(SIGN_IN_ERROR.accountSuspended),
  other_tab: signInPath(),
};

/** The reason a refresh failure ends the Session, or null if it must not. */
function refusalReason(error: unknown): EndSessionReason | null {
  if (!isAxiosError(error) || error.response?.status !== 401) return null;
  const detail = (error.response.data as { detail?: unknown } | undefined)?.detail;
  return detail === SIGN_IN_ERROR.accountSuspended ? 'account_suspended' : 'session_ended';
}

type Listener = (session: Session | null) => void;

const listeners = new Set<Listener>();
// The Session this tab last saw, so a full `localStorage.clear()` in another
// tab only ends a Session this tab actually had.
let lastSeenSession: Session | null = readSession();

function notify(current: Session | null): void {
  lastSeenSession = current;
  listeners.forEach((listener) => listener(current));
}

// Shared by concurrent callers (several 401s, overlapping focus and periodic checks)
// so a Session ends exactly once. Starting a Session re-arms it.
let ending: Promise<void> | null = null;

function end(reason: EndSessionReason): Promise<void> {
  ending ??= endNow(reason);
  return ending;
}

async function endNow(reason: EndSessionReason): Promise<void> {
  if (reason === 'user') {
    try {
      await api.post('/logout');
    } catch {
      // The Session ends locally even when the backend call fails.
    }
  }
  clearSession();
  sessionStorage.removeItem(POSTHOG_IDENTIFIED_KEY);
  resetPostHog();
  notify(null);
  hardRedirect(ROUTE_AFTER_END[reason]);
}

async function refresh(): Promise<Session> {
  try {
    await performRefresh();
  } catch (error) {
    const reason = refusalReason(error);
    if (reason) await end(reason);
    throw error;
  }
  const current = readSession();
  if (!current) throw new Error('Session missing after refresh');
  notify(current);
  return current;
}

// Endpoints whose 401 is an answer about signing in or out, not an expired
// access token, so they never trigger a refresh.
const NO_REFRESH_PATHS = ['/login', '/refresh-token', '/logout'];

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

let retryInstalled = false;

/**
 * Install the 401 -> refresh -> retry-once interceptor on `api`; call once from `main.tsx`.
 * Lives here because `services/apiService.ts` must not import this module; no queue, as the refresh path de-duplicates.
 */
export function installRefreshOnUnauthorized(): void {
  if (retryInstalled) return;
  retryInstalled = true;
  api.interceptors.response.use(undefined, async (error: unknown) => {
    if (!isAxiosError(error) || error.response?.status !== 401 || !error.config) throw error;
    const config = error.config as RetriableConfig;
    const url = config.url ?? '';
    if (config._retry || NO_REFRESH_PATHS.some((path) => url.includes(path))) throw error;
    const current = readSession();
    if (!current) throw error;
    config._retry = true;
    // A 401 for a token that has since been replaced needs no new refresh.
    const sent = config.headers?.Authorization;
    const token =
      sent && sent !== `Bearer ${current.accessToken}`
        ? current.accessToken
        : (await refresh()).accessToken;
    config.headers.Authorization = `Bearer ${token}`;
    return api(config);
  });
}

// Other tabs: a new value is a Session started or refreshed there; a removal or full clear ends it here.
// Registered at module load so the analytics identity resets even with no subscribers.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.storageArea && event.storageArea !== window.localStorage) return;
    if (event.key !== null && event.key !== SESSION_STORAGE_KEY) return;
    const current = readSession();
    if (current) {
      // A Session started (or refreshed) in another tab can end here again.
      ending = null;
      notify(current);
      return;
    }
    const hadSession = lastSeenSession !== null || (event.key !== null && event.oldValue !== null);
    if (hadSession) void end('other_tab');
  });
}

/** Refresh proactively once the access token is this close to expiry. */
const PROACTIVE_REFRESH_MS = 10 * 60 * 1000;

export const session = {
  get: readSession,
  /** True when there is a Session whose access token is near or past expiry. */
  needsRefresh(): boolean {
    const current = readSession();
    if (!current) return false;
    return new Date(current.expiresAt).getTime() <= Date.now() + PROACTIVE_REFRESH_MS;
  },
  /** Start a Session from an access token and its ISO expiry. */
  start(accessToken: string, expiresAt: string): void {
    const current = { accessToken, expiresAt };
    writeSession(current);
    ending = null;
    notify(current);
  },
  /**
   * Start a Session from a callback fragment (`#access_token=…&token_type=Bearer&expires_at=<ISO>`).
   * On failure it starts nothing and returns the reason for a sign-in page error.
   */
  startFromFragment(fragment: string): StartFromFragmentResult {
    const params = new URLSearchParams(fragment.replace(/^#/, ''));
    const accessToken = params.get('access_token');
    const expiresAt = params.get('expires_at');
    if (!accessToken) return { ok: false, reason: 'missing_token' };
    if (!expiresAt || Number.isNaN(Date.parse(expiresAt))) {
      return { ok: false, reason: 'invalid_expiry' };
    }
    session.start(accessToken, expiresAt);
    return { ok: true };
  },
  /**
   * Refresh through the single refresh path. A 401 ends the Session; any other
   * failure (network, 5xx) leaves it in place. Rejects on every failure.
   */
  refresh,
  /** End the Session for `reason`: clear storage, reset analytics, route away. */
  end,
  /** Listen for Session changes in this tab and others. Returns unsubscribe. */
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
