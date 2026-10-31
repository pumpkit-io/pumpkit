import { useCallback, useEffect, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { track } from '@/lib/analytics';
import { timeOfDay } from '@/lib/relativeTime';
import { errorMessage, errorRetryAt, errorStatus } from '@/services/apiErrors';
import {
  inspirationAuthorService,
  type InspirationAuthor,
} from '@/services/inspirationAuthorService';

type LookupResult = 'found' | 'missing' | 'private' | 'no_posts' | 'limited';

/** What a refused lookup tells the funnel, or null when the refusal came before any lookup. */
function lookupResult(e: unknown): LookupResult | null {
  const status = errorStatus(e);
  if (status === 404) return 'missing';
  if (status === 429) return 'limited';
  // Both answers are 422s; only the sentence tells a private account from one with no posts.
  if (status === 422) return errorMessage(e, '').includes('is private') ? 'private' : 'no_posts';
  return null;
}

/** The User's Inspiration authors, loaded on mount, with add, refresh and remove. */
export function useInspirationAuthors() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const [authors, setAuthors] = useState<InspirationAuthor[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  /** The handle being added, whose posts are being read. */
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  /** Why a refresh was held back, which is not an error. */
  const [notice, setNotice] = useState<string | null>(null);

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

  /**
   * Resolves true once the author is on the list. `lookup` says the User asked to look the handle
   * up on X rather than picking it from the Author directory.
   */
  const add = useCallback(
    async (handle: string, { lookup = false }: { lookup?: boolean } = {}): Promise<boolean> => {
      setAdding(handle.trim().replace(/^@/, '').toLowerCase());
      setError(null);
      setNotice(null);
      try {
        const added = await inspirationAuthorService.add(handle);
        setAuthors((list) => [...(list ?? []).filter((a) => a.handle !== added.handle), added]);
        track('inspiration_author_added');
        if (lookup) track('author_looked_up', { result: 'found' });
        return true;
      } catch (e) {
        const result = lookup ? lookupResult(e) : null;
        if (result) track('author_looked_up', { result });
        fail(e, "Couldn't add that handle. Try again.");
        return false;
      } finally {
        setAdding(null);
      }
    },
    [fail],
  );

  const refresh = useCallback(
    async (handle: string) => {
      setRefreshing(handle);
      setError(null);
      setNotice(null);
      try {
        const refreshed = await inspirationAuthorService.refresh(handle);
        setAuthors((list) =>
          (list ?? []).map((a) => (a.handle === refreshed.handle ? refreshed : a)),
        );
        track('inspiration_authors_refreshed');
      } catch (e) {
        const retryAt = errorRetryAt(e);
        if (retryAt) {
          setNotice(
            `${errorMessage(e, `@${handle} was fetched less than an hour ago.`)} ` +
              `You can refresh it again at ${timeOfDay(retryAt)}.`,
          );
        } else {
          fail(e, `Couldn't refresh @${handle}. Try again.`);
        }
      } finally {
        setRefreshing(null);
      }
    },
    [fail],
  );

  const remove = useCallback(
    async (handle: string) => {
      setError(null);
      setNotice(null);
      try {
        await inspirationAuthorService.remove(handle);
        setAuthors((list) => (list ?? []).filter((a) => a.handle !== handle));
        track('inspiration_author_removed');
      } catch (e) {
        fail(e, `Couldn't remove @${handle}. Try again.`);
      }
    },
    [fail],
  );

  return { authors, loadFailed, adding, refreshing, error, notice, add, refresh, remove };
}
