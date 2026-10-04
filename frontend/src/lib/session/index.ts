import { isAxiosError, type InternalAxiosRequestConfig } from 'axios';
import { hardRedirect } from '@/lib/navigation';
import { resetPostHog } from '@/lib/posthog';
import { storageKey } from '@/lib/storage';
import { api, performRefresh } from '@/services/apiService';
import {
  clearSession,
  readSession,
  SESSION_STORAGE_KEY,
  writeSession,
  type Session,
} from './store';

export type { Session } from './store';

/**
 * Why a Session ended. These are the only ways a Session ends.
 * - `user`: the User signed out (also calls backend logout).
 * - `session_ended`: the refresh endpoint answered 401.
 * - `account_suspended`: the refresh endpoint answered 401 because the User is Suspended.
 * - `other_tab`: Session storage was cleared in another tab.
 */
export type EndSessionReason = 'user' | 'session_ended' | 'account_suspended' | 'other_tab';

const POSTHOG_IDENTIFIED_KEY = storageKey('posthog-identified');

/** Where the browser goes after a Session ends, per reason. */
const ROUTE_AFTER_END: Record<EndSessionReason, string> = {
  user: '/login',
  session_ended: '/login',
  account_suspended: '/login?error=account_suspended',
  other_tab: '/login',
};

/** The reason a refresh failure ends the Session, or null if it must not. */
function refusalReason(error: unknown): EndSessionReason | null {
  if (!isAxiosError(error) || error.response?.status !== 401) return null;
  const detail = (error.response.data as { detail?: unknown } | undefined)?.detail;
  return detail === 'account_suspended' ? 'account_suspended' : 'session_ended';
}

type Listener = (session: Session | null) => void;

const listeners = new Set<Listener>();
// The Session this tab last saw, so a full `localStorage.clear()` in another
// tab only ends a Session this tab actually had.
let known: Session | null = readSession();

function notify(current: Session | null): void {
  known = current;
  listeners.forEach((listener) => listener(current));
}

async function end(reason: EndSessionReason): Promise<void> {
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

// A protected request answered 401 awaits a refresh and retries once. The
// shared refresh path de-duplicates concurrent callers, and `refresh` applies
// the sign-out rule, so this interceptor has no queue and no rule of its own.
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

// Other tabs: a new value is a Session started or refreshed elsewhere; a
// removed value (or a full clear) ends the Session here too. Registered once,
// so the analytics identity is reset even if nothing has subscribed.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.storageArea && event.storageArea !== window.localStorage) return;
    if (event.key !== null && event.key !== SESSION_STORAGE_KEY) return;
    const current = readSession();
    if (current) {
      notify(current);
      return;
    }
    const hadSession = known !== null || (event.key !== null && event.oldValue !== null);
    if (hadSession) void end('other_tab');
  });
}

/** Refresh proactively once the access token is this close to expiry. */
const PROACTIVE_REFRESH_MS = 10 * 60 * 1000;

export const session = {
  /** The current Session, or null when signed out. */
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
    notify(current);
  },
  /**
   * Start a Session from a sign-in callback's URL fragment
   * (`#access_token=…&token_type=Bearer&expires_at=<ISO>`). Returns false,
   * starting nothing, when the token or a parseable expiry is missing.
   */
  startFromFragment(fragment: string): boolean {
    const params = new URLSearchParams(fragment.replace(/^#/, ''));
    const accessToken = params.get('access_token');
    const expiresAt = params.get('expires_at');
    if (!accessToken || !expiresAt || Number.isNaN(Date.parse(expiresAt))) return false;
    session.start(accessToken, expiresAt);
    return true;
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
