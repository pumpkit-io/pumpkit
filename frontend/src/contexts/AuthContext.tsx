import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { userService } from '../services/userService';
import { identifyUser } from '../lib/posthog';
import { POSTHOG_IDENTIFIED_KEY, session } from '../lib/session';

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
    // Best-effort: if /users/me fails, the next login or refresh retries.
    return false;
  }
}

type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Dev-only: with VITE_BYPASS_AUTH=true, protected pages render without a real Session.
// The `import.meta.env.DEV` guard strips this from production builds.
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

  // No Session means signed out with no network call; one near expiry is refreshed first.
  // Only a 401 ends the Session; other failures retry on the next 401, focus or interval.
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

  useEffect(() => {
    if (status !== 'authenticated') return;
    const interval = setInterval(() => {
      checkTokenRefresh();
    }, 60_000);
    return () => clearInterval(interval);
  }, [status, checkTokenRefresh]);

  // The flag avoids a `$set` on every reload: PostHog re-emits it even for an unchanged distinct_id.
  // Ending a Session clears the flag; AccountDialog re-identifies itself after a profile save.
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

  // Ending a Session clears storage, resets the analytics identity and routes to sign-in.
  const logout = () => session.end('user');

  const value: AuthContextType = {
    isAuthenticated: status === 'authenticated',
    isLoading: status === 'loading',
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
