import { useCallback, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import {
  scheduledPostService,
  type Destination,
  type PostText,
  type ScheduledPost,
} from '@/services/scheduledPostService';
import { PROFILE } from './communities';
import { pastCommunitiesChanged } from './usePastCommunities';

/** What a Post now that comes back scheduled means: the publisher retries it. */
export const X_BUSY_NOTICE = 'X was busy. Pumpkit will keep trying for the next 15 minutes.';

export type NewScheduledPost = PostText & {
  /** The User's profile when left out. */
  destination?: Destination;
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
      const { destination = PROFILE } = request;
      const post: PostText =
        'sourceVersionId' in request
          ? { sourceVersionId: request.sourceVersionId }
          : { parts: request.parts };
      setSending(true);
      setError(null);
      try {
        const created = request.postNow
          ? await scheduledPostService.postNow(post, destination)
          : await scheduledPostService.schedule(post, request.publishAt, destination);
        track('scheduled_post_created', {
          format: created.parts.length > 1 ? 'thread' : 'post',
          part_count: created.parts.length,
          source: 'sourceVersionId' in post ? 'final' : 'typed',
          post_now: request.postNow,
          ...(destination.community
            ? { destination: 'community', share_with_followers: destination.shareWithFollowers }
            : { destination: 'profile' }),
        });
        if (destination.community) pastCommunitiesChanged();
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
