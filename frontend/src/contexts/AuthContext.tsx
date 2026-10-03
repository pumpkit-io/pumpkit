import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { authService } from '../services/authService';
import { userService } from '../services/userService';
import { identifyUser, resetPostHog } from '../lib/posthog';
import { storageKey } from '../lib/storage';

const POSTHOG_IDENTIFIED_KEY = storageKey('posthog-identified');

async function identifyFromBackend(): Promise<boolean> {
  try {
    const profile = await userService.fetchProfile();
    // Use email as distinct_id — stable for the lifetime of an account and
    // already returned by /users/me. If you ever need to support email
    // changes without losing continuity, swap to a server-issued user_id.
    identifyUser(profile.email, {
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

// Drop a dead session so reloads don't make a guaranteed-401 /refresh-token call.
function clearStoredTokens() {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('token_expires_at');
}

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (token: string, expiresAt?: string) => void;
  logout: () => Promise<void>;
  tokenExpiration: Date | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Dev-only escape hatch: render auth-protected pages without a real session.
// Active only when the dev server is running AND VITE_BYPASS_AUTH=true. The
// `import.meta.env.DEV` guard means production builds dead-code-eliminate this.
export const BYPASS_AUTH = import.meta.env.DEV && import.meta.env.VITE_BYPASS_AUTH === 'true';
if (BYPASS_AUTH) {
  // eslint-disable-next-line no-console
  console.warn('[auth] VITE_BYPASS_AUTH is ON — all routes treated as authenticated. Dev only.');
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(BYPASS_AUTH ? 'authenticated' : 'loading');
  const [tokenExpiration, setTokenExpiration] = useState<Date | null>(() =>
    authService.getTokenExpiration(),
  );

  // Bootstrap on mount.
  //
  // Source of truth for "am I logged in": a valid (non-expired) access token
  // in localStorage. If we have one, mark authenticated immediately and let
  // the periodic interval handle proactive refresh near expiry.
  //
  // If we don't have a valid local access token, attempt /refresh-token once.
  // The refresh token lives in an HttpOnly cookie — we can't see it from JS,
  // but the browser will send it. Success → fresh access token, stay logged in.
  // Failure → unauthenticated.
  //
  // Refresh failure with a valid access token still present means "can't extend
  // the session right now" — it does NOT mean "log out". The access token is
  // still good until it expires; the response interceptor will retry refresh
  // on the next 401. Importantly, this avoids tearing down the session if a
  // refresh call ever fails for transient reasons.
  useEffect(() => {
    if (BYPASS_AUTH) return;
    let cancelled = false;
    (async () => {
      // No access token in localStorage → no prior session evidence. Skip
      // the speculative refresh entirely. (Even if a refresh cookie still
      // exists in the browser from a previous logged-out session, calling
      // /refresh-token will just generate a 401 — wasteful and noisy.)
      // logout() clears the access token, so this branch covers logged-out
      // and never-logged-in users.
      if (!localStorage.getItem('auth_token')) {
        if (!cancelled) {
          setStatus('unauthenticated');
          setTokenExpiration(null);
        }
        return;
      }

      // We have a token. If it's still well within its lifetime, just trust it.
      if (!authService.needsRefresh()) {
        if (!cancelled) {
          setStatus('authenticated');
          setTokenExpiration(authService.getTokenExpiration());
        }
        return;
      }

      // Token is near expiry or expired — try to refresh.
      try {
        await authService.refreshToken();
        if (!cancelled) {
          setStatus('authenticated');
          setTokenExpiration(authService.getTokenExpiration());
        }
      } catch {
        if (!cancelled) {
          if (authService.isAuthenticated()) {
            setStatus('authenticated');
            setTokenExpiration(authService.getTokenExpiration());
          } else {
            clearStoredTokens();
            setStatus('unauthenticated');
            setTokenExpiration(null);
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const checkTokenRefresh = useCallback(async () => {
    if (!authService.needsRefresh()) return;
    try {
      await authService.refreshToken();
      setTokenExpiration(authService.getTokenExpiration());
      setStatus('authenticated');
    } catch {
      // Refresh failed. If the access token is still valid, keep the session
      // alive — we'll retry on the next interval / 401. Only log out once the
      // access token is truly gone.
      if (!authService.isAuthenticated()) {
        clearStoredTokens();
        setStatus('unauthenticated');
        setTokenExpiration(null);
      }
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
  // distinct_id is unchanged). The flag is cleared on logout, and
  // AccountDialog clears it after a profile save to force a refresh.
  useEffect(() => {
    if (BYPASS_AUTH) return;
    if (status !== 'authenticated') return;
    if (sessionStorage.getItem(POSTHOG_IDENTIFIED_KEY) === '1') return;
    void identifyFromBackend().then((ok) => {
      if (ok) sessionStorage.setItem(POSTHOG_IDENTIFIED_KEY, '1');
    });
  }, [status]);

  // Cross-tab sync + focus refresh. Both attempt refresh on stale tokens
  // rather than synchronously logging the user out.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== 'auth_token' && e.key !== 'token_expires_at' && e.key !== null) return;
      if (!localStorage.getItem('auth_token')) {
        setStatus('unauthenticated');
        setTokenExpiration(null);
      } else if (authService.isAuthenticated()) {
        setStatus('authenticated');
        setTokenExpiration(authService.getTokenExpiration());
      } else {
        checkTokenRefresh();
      }
    };
    const onFocus = () => {
      checkTokenRefresh();
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', onFocus);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', onFocus);
    };
  }, [checkTokenRefresh]);

  const login = (token: string, expiresAt?: string) => {
    localStorage.setItem('auth_token', token);
    if (expiresAt) localStorage.setItem('token_expires_at', expiresAt);
    setStatus('authenticated');
    setTokenExpiration(authService.getTokenExpiration());
  };

  const logout = async () => {
    try {
      await authService.logout();
    } catch {
      // continue with local cleanup
    }
    setStatus('unauthenticated');
    setTokenExpiration(null);
    sessionStorage.removeItem(POSTHOG_IDENTIFIED_KEY);
    resetPostHog();
  };

  const value: AuthContextType = {
    isAuthenticated: status === 'authenticated',
    isLoading: status === 'loading',
    login,
    logout,
    tokenExpiration,
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
