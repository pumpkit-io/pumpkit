import { useCallback, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';

/** What a Post now that comes back scheduled means: the publisher retries it. */
export const X_BUSY_NOTICE = 'X was busy. Pumpkit will keep trying for the next 15 minutes.';

export type NewScheduledPost = {
  text: string;
  /** The Version whose Final the text is, when it is one. */
  sourceVersionId?: string;
} & ({ postNow: true } | { postNow: false; publishAt: string });

export type CreateOutcome =
  | { kind: 'created'; scheduledPost: ScheduledPost }
  | { kind: 'notSubscribed' }
  | { kind: 'refused' };

/**
 * Sends a new Scheduled post from the composer or a Final. A refusal sets `error`, except one
 * for want of a Subscription, which the caller turns into the prompt to subscribe.
 */
export function useCreateScheduledPost() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const { reload: reloadXConnection } = useXConnectionContext();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(
    async (request: NewScheduledPost): Promise<CreateOutcome> => {
      const { text, sourceVersionId } = request;
      setSending(true);
      setError(null);
      try {
        const created = request.postNow
          ? await scheduledPostService.postNow(text, sourceVersionId)
          : await scheduledPostService.schedule(text, request.publishAt, sourceVersionId);
        track('scheduled_post_created', {
          source: sourceVersionId ? 'final' : 'typed',
          post_now: request.postNow,
        });
        // A Failed one may have flagged the X connection for reconnecting.
        if (created.state === 'failed') void reloadXConnection();
        return { kind: 'created', scheduledPost: created };
      } catch (e) {
        if (errorStatus(e) === 403) {
          refreshSubscribed();
          return { kind: 'notSubscribed' };
        }
        setError(
          errorMessage(
            e,
            request.postNow
              ? "Couldn't post to X. Please try again."
              : "Couldn't schedule the post. Please try again.",
          ),
        );
        // A 409 may mean the X connection changed elsewhere: show its current state.
        if (errorStatus(e) === 409) void reloadXConnection();
        return { kind: 'refused' };
      } finally {
        setSending(false);
      }
    },
    [refreshSubscribed, reloadXConnection],
  );

  return { sending, error, create };
}
