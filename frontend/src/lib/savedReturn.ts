import { storage, type StorageKey } from './storage';

// Long enough for a Magic link or X's consent screen, short enough that an abandoned one
// doesn't steer a later visit.
const MAX_AGE_MS = 30 * 60 * 1000;

interface SavedReturn {
  path: string;
  savedAt: number;
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
 * A page to come back to after leaving the app, kept in localStorage under `key` for 30 minutes.
 * Only paths `allowed` accepts are kept or given back, so a stored value can't send the User away.
 */
export function savedReturn(key: StorageKey, allowed: (path: string) => boolean) {
  const forget = (): void => tolerant(() => storage.remove(key), undefined);
  return {
    remember(path: string): void {
      if (!allowed(path)) return;
      tolerant(() => storage.set<SavedReturn>(key, { path, savedAt: Date.now() }), undefined);
    },

    forget,

    /** The saved path if it is still fresh, clearing it either way. */
    take(): string | null {
      const saved = tolerant(() => storage.get<Partial<SavedReturn> | null>(key, null), null);
      forget();
      if (typeof saved?.path !== 'string' || typeof saved.savedAt !== 'number') return null;
      const age = Date.now() - saved.savedAt;
      if (age < 0 || age > MAX_AGE_MS) return null;
      return allowed(saved.path) ? saved.path : null;
    },
  };
}
