import { storage, storageKey } from '@/lib/storage';

/**
 * The only code that reads or writes the access token in storage; everything else uses `@/lib/session`.
 * Imports nothing from the HTTP layer so `services/apiService.ts` can use it without an import cycle.
 */

export interface Session {
  accessToken: string;
  /** ISO 8601 expiry of the access token, as returned by the backend. */
  expiresAt: string;
}

/** The fully-qualified localStorage key, for matching storage events. */
export const SESSION_STORAGE_KEY = storageKey('session');

export function readSession(): Session | null {
  const value = storage.get<Partial<Session> | null>('session', null);
  if (!value || typeof value.accessToken !== 'string' || typeof value.expiresAt !== 'string') {
    return null;
  }
  return { accessToken: value.accessToken, expiresAt: value.expiresAt };
}

export function writeSession(session: Session): void {
  storage.set<Session>('session', session);
}

export function clearSession(): void {
  storage.remove('session');
}
