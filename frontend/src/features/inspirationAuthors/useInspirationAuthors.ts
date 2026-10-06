import { useCallback, useEffect, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import {
  inspirationAuthorService,
  type InspirationAuthor,
} from '@/services/inspirationAuthorService';

/** The User's Inspiration authors, loaded on mount, with add and remove. */
export function useInspirationAuthors() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const [authors, setAuthors] = useState<InspirationAuthor[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    inspirationAuthorService
      .list()
      .then((list) => !cancelled && setAuthors(list))
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

  /** Resolves true once the author is on the list. */
  const add = useCallback(
    async (handle: string): Promise<boolean> => {
      setIsAdding(true);
      setError(null);
      try {
        const added = await inspirationAuthorService.add(handle);
        setAuthors((list) => [...(list ?? []).filter((a) => a.handle !== added.handle), added]);
        track('inspiration_author_added');
        return true;
      } catch (e) {
        fail(e, "Couldn't add that handle. Please try again.");
        return false;
      } finally {
        setIsAdding(false);
      }
    },
    [fail],
  );

  const remove = useCallback(
    async (handle: string) => {
      setError(null);
      try {
        await inspirationAuthorService.remove(handle);
        setAuthors((list) => (list ?? []).filter((a) => a.handle !== handle));
        track('inspiration_author_removed');
      } catch (e) {
        fail(e, `Couldn't remove @${handle}. Please try again.`);
      }
    },
    [fail],
  );

  return { authors, loadFailed, isAdding, error, add, remove };
}
