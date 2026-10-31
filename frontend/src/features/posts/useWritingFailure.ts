import { useCallback, useState } from 'react';
import { useAllowanceUsedUp } from '@/features/billing/useAllowanceUsedUp';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { timeOfDay } from '@/lib/relativeTime';
import { errorMessage, errorRetryAt, errorStatus } from '@/services/apiErrors';

/** A 4xx: the backend turned the request down before writing anything, so no Version failed. */
export function isRefusal(e: unknown): boolean {
  const status = errorStatus(e);
  return status !== null && status >= 400 && status < 500;
}

/** How writing a Version went wrong, shared by starting a Post and giving Feedback. */
export function useWritingFailure() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const [error, setError] = useState<string | null>(null);
  // The hourly limit on attempts: not an error, since trying again before `retry_at` won't help.
  const [notice, setNotice] = useState<string | null>(null);
  // No Generation left until the Allowance period resets.
  const { allowanceUsedUp, caught, clear: clearUsedUp } = useAllowanceUsedUp();

  const fail = useCallback(
    (e: unknown, fallback: string) => {
      // A refusal for want of a Subscription shows the prompt to subscribe, not an error.
      if (errorStatus(e) === 403) {
        refreshSubscribed();
        return;
      }
      if (caught(e)) return;
      const retryAt = errorRetryAt(e);
      if (retryAt)
        setNotice(`${errorMessage(e, fallback)} You can write again at ${timeOfDay(retryAt)}.`);
      else setError(errorMessage(e, fallback));
    },
    [refreshSubscribed, caught],
  );

  const clear = useCallback(() => {
    setError(null);
    setNotice(null);
    clearUsedUp();
  }, [clearUsedUp]);

  return { error, notice, allowanceUsedUp, fail, clear };
}
