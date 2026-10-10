import { useCallback, useEffect, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';

/** The User's Scheduled posts, loaded on mount, with Post now, Schedule, edit and cancel. */
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

  /**
   * Sends a new Scheduled post and lists it. Resolves to whether it went the way the User
   * asked (Published, or scheduled), so the composer knows to clear itself.
   */
  const create = useCallback(
    async (postNow: boolean, send: () => Promise<ScheduledPost>): Promise<boolean> => {
      setPosting(true);
      setError(null);
      try {
        const created = await send();
        track('scheduled_post_created', { source: 'typed', post_now: postNow });
        setScheduledPosts((current) => [created, ...(current ?? [])]);
        // A Failed one may have flagged the X connection for reconnecting.
        if (created.state === 'failed') void reloadXConnection();
        return created.state !== 'failed';
      } catch (e) {
        if (errorStatus(e) === 403) {
          refreshSubscribed();
        } else {
          setError(
            errorMessage(
              e,
              postNow
                ? "Couldn't post to X. Please try again."
                : "Couldn't schedule the post. Please try again.",
            ),
          );
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

  const postNow = useCallback(
    (text: string) => create(true, () => scheduledPostService.postNow(text)),
    [create],
  );

  /** `publishAt` is an ISO instant on a whole minute. */
  const schedule = useCallback(
    (text: string, publishAt: string) =>
      create(false, () => scheduledPostService.schedule(text, publishAt)),
    [create],
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
        track('scheduled_post_edited', { rescheduled: changes.publishAt !== undefined });
        setScheduledPosts((current) => current?.map((p) => (p.id === id ? edited : p)));
      }, "Couldn't save the changes. Please try again."),
    [change],
  );

  const cancel = useCallback(
    (id: string) =>
      change(async () => {
        await scheduledPostService.cancel(id);
        track('scheduled_post_cancelled');
        setScheduledPosts((current) => current?.filter((p) => p.id !== id));
      }, "Couldn't cancel the post. Please try again."),
    [change],
  );

  return { scheduledPosts, loadFailed, posting, error, postNow, schedule, edit, cancel };
}
