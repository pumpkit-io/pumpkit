import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { showToast } from '@/components/Toaster';
import { storage } from '@/lib/storage';

// Long enough for X's consent screen, short enough that an abandoned one doesn't steer later.
const MAX_AGE_MS = 30 * 60 * 1000;

interface SavedReturn {
  path: string;
  savedAt: number;
}

/** Only a Post's page, so a stored value can't send the User elsewhere. */
function isPostPage(path: string): boolean {
  return /^\/posts\/[\w-]+$/.test(path);
}

function tolerant<T>(call: () => T, fallback: T): T {
  try {
    return call();
  } catch {
    return fallback;
  }
}

/**
 * The Post page to come back to after X's consent screen, kept in localStorage across X's
 * redirect. Without one, the X callback lands on Settings.
 */
export const xConnectionReturn = {
  remember(path: string): void {
    if (!isPostPage(path)) return;
    tolerant(
      () => storage.set<SavedReturn>('x-connection-return', { path, savedAt: Date.now() }),
      undefined,
    );
  },

  forget(): void {
    tolerant(() => storage.remove('x-connection-return'), undefined);
  },

  /** The saved path if it is still fresh, clearing it either way. */
  take(): string | null {
    const saved = tolerant(
      () => storage.get<Partial<SavedReturn> | null>('x-connection-return', null),
      null,
    );
    xConnectionReturn.forget();
    if (typeof saved?.path !== 'string' || typeof saved.savedAt !== 'number') return null;
    const age = Date.now() - saved.savedAt;
    if (age < 0 || age > MAX_AGE_MS) return null;
    return isPostPage(saved.path) ? saved.path : null;
  },
};

/** What the X callback hands the page it returns to. */
export interface XConnectionNoticeState {
  xConnectionNotice?: string;
}

/** Shows the X callback's message on a Post page once, then drops it so a reload doesn't repeat it. */
export function useXConnectionNotice(): void {
  const location = useLocation();
  const navigate = useNavigate();
  const notice = (location.state as XConnectionNoticeState | null)?.xConnectionNotice;
  useEffect(() => {
    if (!notice) return;
    showToast(notice);
    navigate(location.pathname, { replace: true, state: null });
  }, [notice, location.pathname, navigate]);
}
