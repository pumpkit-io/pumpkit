import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { userService } from '../services/userService';
import { identifyUser } from '../lib/posthog';
import { session } from '../lib/session';
import { storageKey } from '../lib/storage';

const POSTHOG_IDENTIFIED_KEY = storageKey('posthog-identified');

async function identifyFromBackend(): Promise<boolean> {
  try {
    const profile = await userService.fetchProfile();
    // The User ID is the distinct_id: stable even if the email changes, and
    // not itself an email address. The email stays a person property.
    identifyUser(profile.id, {
      email: profile.email,
      first_name: profile.firstName,
      last_name: profile.lastName,
    });
    return true;
  } catch {
    // Identify is best-effort — if /users/me fails (network, 401 from a
    // stale token, etc.) we let the next login/refresh retry.
    return false;
  }
}

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (token: string, expiresAt: string) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Dev-only escape hatch: render auth-protected pages without a real session.
// Active only when the dev server is running AND VITE_BYPASS_AUTH=true. The
// `import.meta.env.DEV` guard means production builds dead-code-eliminate this.
export const BYPASS_AUTH = import.meta.env.DEV && import.meta.env.VITE_BYPASS_AUTH === 'true';
if (BYPASS_AUTH) {
  console.warn('[auth] VITE_BYPASS_AUTH is ON — all routes treated as authenticated. Dev only.');
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(BYPASS_AUTH ? 'authenticated' : 'loading');

  // The Session module is the source of truth; this context mirrors it.
  useEffect(() => {
    if (BYPASS_AUTH) return;
    return session.subscribe((current) => {
      setStatus(current ? 'authenticated' : 'unauthenticated');
    });
  }, []);

  // Bootstrap on mount. No Session → signed out, with no network call. A
  // Session near or past expiry is refreshed first. The Session module decides
  // whether a failed refresh ends the Session (only a 401 does); otherwise the
  // Session stays and refresh is retried on the next 401, focus or interval.
  useEffect(() => {
    if (BYPASS_AUTH) return;
    let cancelled = false;
    (async () => {
      if (session.needsRefresh()) {
        try {
          await session.refresh();
        } catch {
          // Transient failures keep the Session; a 401 has already ended it.
        }
      }
      if (!cancelled) setStatus(session.get() ? 'authenticated' : 'unauthenticated');
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const checkTokenRefresh = useCallback(async () => {
    if (!session.needsRefresh()) return;
    try {
      await session.refresh();
    } catch {
      // Same rule as bootstrap: the Session module decides whether it ended.
    }
  }, []);

  // Periodic refresh while authenticated.
  useEffect(() => {
    if (status !== 'authenticated') return;
    const interval = setInterval(() => {
      checkTokenRefresh();
    }, 60_000);
    return () => clearInterval(interval);
  }, [status, checkTokenRefresh]);

  // Identify the PostHog person whenever we become authenticated. Gated by
  // a session-scoped flag so we don't fire a `$set` event on every page
  // reload (PostHog re-emits $set for property updates even when the
  // distinct_id is unchanged). The Session module clears the flag whenever a
  // Session ends, and AccountDialog clears it after a profile save.
  useEffect(() => {
    if (BYPASS_AUTH) return;
    if (status !== 'authenticated') return;
    if (sessionStorage.getItem(POSTHOG_IDENTIFIED_KEY) === '1') return;
    void identifyFromBackend().then((ok) => {
      if (ok) sessionStorage.setItem(POSTHOG_IDENTIFIED_KEY, '1');
    });
  }, [status]);

  // Refresh on focus. Cross-tab changes reach us through the subscription.
  useEffect(() => {
    const onFocus = () => {
      checkTokenRefresh();
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [checkTokenRefresh]);

  const login = (token: string, expiresAt: string) => {
    session.start(token, expiresAt);
  };

  // Ending a Session clears storage, resets the analytics identity and routes
  // to the sign-in page.
  const logout = () => session.end('user');

  const value: AuthContextType = {
    isAuthenticated: status === 'authenticated',
    isLoading: status === 'loading',
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
