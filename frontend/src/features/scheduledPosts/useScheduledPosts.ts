import { useCallback, useEffect, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import {
  scheduledPostService,
  type ScheduledPost,
  type ScheduledPostChanges,
} from '@/services/scheduledPostService';
import { pastCommunitiesChanged } from './usePastCommunities';

/** The User's Scheduled posts, loaded on mount, with edit and cancel. */
export function useScheduledPosts() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const { reload: reloadXConnection } = useXConnectionContext();
  /** Undefined while loading. */
  const [scheduledPosts, setScheduledPosts] = useState<ScheduledPost[] | undefined>(undefined);
  const [loadFailed, setLoadFailed] = useState(false);

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

  /**
   * Runs a change to a listed Scheduled post. Resolves to null once done, or to why it was
   * refused; a 409 means its state moved on, so the list is reloaded to show where it is now.
   */
  const change = useCallback(
    async (run: () => Promise<void>, fallback: string): Promise<string | null> => {
      try {
        await run();
        return null;
      } catch (e) {
        if (errorStatus(e) === 403) refreshSubscribed();
        if (errorStatus(e) === 409) {
          scheduledPostService
            .list()
            .then(setScheduledPosts)
            .catch(() => undefined);
          void reloadXConnection();
        }
        return errorMessage(e, fallback);
      }
    },
    [refreshSubscribed, reloadXConnection],
  );

  const edit = useCallback(
    (id: string, changes: ScheduledPostChanges) =>
      change(async () => {
        const edited = await scheduledPostService.edit(id, changes);
        setScheduledPosts((current) => current?.map((p) => (p.id === id ? edited : p)));
        if (changes.community) pastCommunitiesChanged();
      }, "Couldn't save the changes. Please try again."),
    [change],
  );

  /** Cancels a scheduled one, or removes a Failed one. */
  const cancel = useCallback(
    (id: string) =>
      change(async () => {
        await scheduledPostService.cancel(id);
        setScheduledPosts((current) => current?.filter((p) => p.id !== id));
      }, "Couldn't remove the post. Please try again."),
    [change],
  );

  return { scheduledPosts, loadFailed, edit, cancel };
}
