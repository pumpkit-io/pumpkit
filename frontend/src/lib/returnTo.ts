import { storage } from './storage';

/** The pages a signed-out User may come back to after sign-in. */
const RESUMABLE_PATHS = ['/oauth/consent'];
// An authorization request lives 30 minutes, long enough for a Magic link.
const MAX_AGE_MS = 30 * 60 * 1000;

interface SavedReturn {
  path: string;
  savedAt: number;
}

/** Only an internal path to an allowlisted page, so a stored value can't send the User away. */
function isResumable(path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//')) return false;
  return RESUMABLE_PATHS.includes(path.split(/[?#]/, 1)[0]);
}

/**
 * The page to land on after sign-in, kept in localStorage so it survives Google's redirect and a
 * Magic link opened in the same browser. A Magic link opened on another device lands on New post.
 */
export const returnTo = {
  /** Saves `path` (pathname and search) when it is a page worth coming back to. */
  remember(path: string): void {
    if (isResumable(path)) storage.set<SavedReturn>('return-to', { path, savedAt: Date.now() });
  },

  /** The saved path if it is still fresh, clearing it either way. */
  take(): string | null {
    const saved = storage.get<Partial<SavedReturn> | null>('return-to', null);
    storage.remove('return-to');
    if (typeof saved?.path !== 'string' || typeof saved.savedAt !== 'number') return null;
    const age = Date.now() - saved.savedAt;
    if (age < 0 || age > MAX_AGE_MS) return null;
    return isResumable(saved.path) ? saved.path : null;
  },
};
