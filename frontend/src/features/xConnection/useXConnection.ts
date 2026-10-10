import { useCallback, useEffect, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';

/** The User's X connection, loaded on mount, with connect and disconnect. */
export function useXConnection() {
  const { refresh: refreshSubscribed } = useSubscribed();
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
      if (errorStatus(e) === 403) {
        setError(null);
        refreshSubscribed();
      } else {
        setError(errorMessage(e, fallback));
      }
    },
    [refreshSubscribed],
  );

  /** Leaves for X's consent screen, which comes back through /oauth/x/callback. */
  const connect = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      redirectTo(await xConnectionService.startAuthorization());
    } catch (e) {
      fail(e, "Couldn't start connecting X. Please try again.");
      setBusy(false);
    }
  }, [fail]);

  const disconnect = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await xConnectionService.disconnect();
      setConnection(null);
      track('x_disconnected');
    } catch (e) {
      fail(e, "Couldn't disconnect X. Please try again.");
    } finally {
      setBusy(false);
    }
  }, [fail]);

  /** Picks up a change the backend made, such as flagging the X connection for reconnecting. */
  const reload = useCallback(async () => {
    try {
      setConnection(await xConnectionService.get());
    } catch {
      // The X connection on screen stays; the next page load tries again.
    }
  }, []);

  return { connection, loadFailed, busy, error, connect, disconnect, reload };
}
