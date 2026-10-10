import { useCallback, useEffect, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';

/** The User's Scheduled posts, loaded on mount, with Post now. */
export function useScheduledPosts() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const { reload: reloadXConnection } = useXConnectionContext();
  /** Undefined while loading. */
  const [scheduledPosts, setScheduledPosts] = useState<ScheduledPost[] | undefined>(undefined);
  const [loadFailed, setLoadFailed] = useState(false);
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    scheduledPostService
      .list()
      .then((found) => !cancelled && setScheduledPosts(found))
      .catch(() => !cancelled && setLoadFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  /** Resolves to whether X published it, so the composer knows to clear its text. */
  const postNow = useCallback(
    async (text: string): Promise<boolean> => {
      setPosting(true);
      setError(null);
      try {
        const posted = await scheduledPostService.postNow(text);
        track('scheduled_post_created', { source: 'typed', post_now: true });
        setScheduledPosts((current) => [posted, ...(current ?? [])]);
        // A Failed one may have flagged the X connection for reconnecting.
        if (posted.state === 'failed') void reloadXConnection();
        return posted.state === 'published';
      } catch (e) {
        if (errorStatus(e) === 403) {
          refreshSubscribed();
        } else {
          setError(errorMessage(e, "Couldn't post to X. Please try again."));
          // A 409 means the X connection changed elsewhere: show its current state.
          if (errorStatus(e) === 409) void reloadXConnection();
        }
        return false;
      } finally {
        setPosting(false);
      }
    },
    [refreshSubscribed, reloadXConnection],
  );

  return { scheduledPosts, loadFailed, posting, error, postNow };
}
