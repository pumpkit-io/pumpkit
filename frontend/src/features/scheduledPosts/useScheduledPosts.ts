import { useCallback, useEffect, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';
import {
  useCreateScheduledPost,
  X_BUSY_NOTICE,
  type NewScheduledPost,
} from './useCreateScheduledPost';

/** The User's Scheduled posts, loaded on mount, with Post now, Schedule, edit and cancel. */
export function useScheduledPosts() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const { reload: reloadXConnection } = useXConnectionContext();
  const { sending: posting, error, create } = useCreateScheduledPost();
  /** Undefined while loading. */
  const [scheduledPosts, setScheduledPosts] = useState<ScheduledPost[] | undefined>(undefined);
  const [loadFailed, setLoadFailed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

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
   * Sends a new Scheduled post and lists it. Resolves to whether it is on its way (Published,
   * or scheduled), so the composer knows to clear itself.
   */
  const add = useCallback(
    async (request: NewScheduledPost): Promise<boolean> => {
      setNotice(null);
      const outcome = await create(request);
      if (outcome.kind !== 'created') return false;
      const created = outcome.scheduledPost;
      setScheduledPosts((current) => [created, ...(current ?? [])]);
      if (request.postNow && created.state === 'scheduled') setNotice(X_BUSY_NOTICE);
      return created.state !== 'failed';
    },
    [create],
  );

  const postNow = useCallback((text: string) => add({ text, postNow: true }), [add]);

  /** `publishAt` is an ISO instant on a whole minute. */
  const schedule = useCallback(
    (text: string, publishAt: string) => add({ text, postNow: false, publishAt }),
    [add],
  );

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
    (id: string, changes: { text?: string; publishAt?: string }) =>
      change(async () => {
        const edited = await scheduledPostService.edit(id, changes);
        setScheduledPosts((current) => current?.map((p) => (p.id === id ? edited : p)));
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

  return { scheduledPosts, loadFailed, posting, error, notice, postNow, schedule, edit, cancel };
}
