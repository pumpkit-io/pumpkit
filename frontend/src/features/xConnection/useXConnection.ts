import { useCallback, useEffect, useState } from 'react';
import { isSubscriptionNeeded } from '@/features/billing/subscriptionNeeded';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import { xConnectionReturn } from './xConnectionReturn';

/** The User's X connection, loaded on mount, with same-account recovery. */
export function useXConnection() {
  const { refresh: refreshOnboarding } = useOnboarding();
  /** Undefined while loading; null when there is none. */
  const [connection, setConnection] = useState<XConnection | null | undefined>(undefined);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    xConnectionService
      .get()
      .then((found) => !cancelled && setConnection(found))
      .catch(() => !cancelled && setLoadFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  /** A refusal for want of a Subscription shows the prompt to subscribe, not an error. */
  const fail = useCallback(
    (e: unknown, fallback: string) => {
      if (isSubscriptionNeeded(e)) {
        setError(null);
        void refreshOnboarding();
      } else {
        setError(errorMessage(e, fallback));
      }
    },
    [refreshOnboarding],
  );

  /**
   * Leaves for X's consent screen, which comes back through /oauth/x/callback, then to
   * `returnPath`, a Post's page, or else to Settings.
   */
  const connect = useCallback(
    async (returnPath?: string) => {
      setBusy(true);
      setError(null);
      if (returnPath) xConnectionReturn.remember(returnPath);
      else xConnectionReturn.forget();
      try {
        redirectTo(await xConnectionService.startAuthorization());
      } catch (e) {
        xConnectionReturn.forget();
        fail(e, "Couldn't start connecting X. Try again.");
        setBusy(false);
      }
    },
    [fail],
  );

  /** Picks up a change the backend made, such as flagging the X connection for reconnecting. */
  const reload = useCallback(async () => {
    try {
      setConnection(await xConnectionService.get());
    } catch {
      // The X connection on screen stays; the next page load tries again.
    }
  }, []);

  return {
    connection,
    loadFailed,
    busy,
    error,
    connect,
    reload,
  };
}
