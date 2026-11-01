import { OAUTH_CONSENT_PATH } from './oauthConsentPath';
import { storage } from './storage';

// An authorization request lives 30 minutes, long enough for a Magic link.
const MAX_AGE_MS = 30 * 60 * 1000;

interface SavedReturn {
  path: string;
  savedAt: number;
}

/** Only an internal path to a consent request, so a stored value can't send the User away. */
function isResumable(path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//')) return false;
  return path.startsWith(`${OAUTH_CONSENT_PATH}?`);
}

/** Runs a storage call; a browser that refuses storage just loses the return. */
function tolerant<T>(call: () => T, fallback: T): T {
  try {
    return call();
  } catch {
    return fallback;
  }
}

/**
 * The page to land on after sign-in, kept in localStorage so it survives Google's redirect and a
 * Magic link opened in the same browser. A Magic link opened on another device lands on New post.
 */
export const returnTo = {
  /** Saves `path` (pathname and search) when it is a page worth coming back to. */
  remember(path: string): void {
    if (!isResumable(path)) return;
    tolerant(() => storage.set<SavedReturn>('return-to', { path, savedAt: Date.now() }), undefined);
  },

  /** Drops the saved path, once the request is decided, expired or used. */
  forget(): void {
    tolerant(() => storage.remove('return-to'), undefined);
  },

  /** The saved path if it is still fresh, clearing it either way. */
  take(): string | null {
    const saved = tolerant(() => storage.get<Partial<SavedReturn> | null>('return-to', null), null);
    returnTo.forget();
    if (typeof saved?.path !== 'string' || typeof saved.savedAt !== 'number') return null;
    const age = Date.now() - saved.savedAt;
    if (age < 0 || age > MAX_AGE_MS) return null;
    return isResumable(saved.path) ? saved.path : null;
  },
};
