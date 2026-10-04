import { APP_SLUG } from './app';

export type StorageKey = 'theme' | 'sidebar-collapsed' | 'posthog-identified' | 'session';

export function storageKey(key: StorageKey): string {
  return `${APP_SLUG}:${key}`;
}

function safeParse<T>(raw: string | null, fallback: T): T {
  if (raw == null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** JSON values in localStorage, namespaced by the app slug. */
export const storage = {
  get<T>(key: StorageKey, fallback: T): T {
    if (typeof window === 'undefined') return fallback;
    return safeParse<T>(window.localStorage.getItem(storageKey(key)), fallback);
  },
  set<T>(key: StorageKey, value: T): void {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(storageKey(key), JSON.stringify(value));
  },
  remove(key: StorageKey): void {
    if (typeof window === 'undefined') return;
    window.localStorage.removeItem(storageKey(key));
  },
};
