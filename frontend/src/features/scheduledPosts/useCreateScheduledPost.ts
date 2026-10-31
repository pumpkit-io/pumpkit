import { useCallback, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { track } from '@/lib/analytics';
import {
  errorAllowanceUsedUp,
  errorMessage,
  errorStatus,
  type AllowanceUsedUp,
} from '@/services/apiErrors';
import { formatOf } from '@/services/postService';
import {
  scheduledPostService,
  type Destination,
  type ScheduledPostSource,
  type ScheduledPost,
} from '@/services/scheduledPostService';
import { PROFILE } from './communities';
import { pastCommunitiesChanged } from './usePastCommunities';

/** What a Post now that comes back scheduled means: the publisher retries it. */
export const X_BUSY_NOTICE = 'X was busy. Pumpkit will keep trying for the next 15 minutes.';

export type NewScheduledPost = ScheduledPostSource & {
  /** The User's profile when left out. */
  destination?: Destination;
} & ({ postNow: true } | { postNow: false; publishAt: string });

export type CreateOutcome =
  | { kind: 'created'; scheduledPost: ScheduledPost }
  | { kind: 'notSubscribed' }
  | { kind: 'refused' };

/**
 * Sends a new Scheduled post copied from the Post's Text. A refusal sets `error`, except one
 * for want of a Subscription, which the caller turns into the prompt to subscribe, and one for
 * want of X posts left, which sets `allowanceUsedUp`.
 */
export function useCreateScheduledPost() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const { reload: reloadXConnection } = useXConnectionContext();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allowanceUsedUp, setAllowanceUsedUp] = useState<AllowanceUsedUp | null>(null);

  const create = useCallback(
    async (request: NewScheduledPost): Promise<CreateOutcome> => {
      const { destination = PROFILE } = request;
      const post: ScheduledPostSource = { postId: request.postId };
      setSending(true);
      setError(null);
      setAllowanceUsedUp(null);
      try {
        const created = request.postNow
          ? await scheduledPostService.postNow(post, destination)
          : await scheduledPostService.schedule(post, request.publishAt, destination);
        track('scheduled_post_created', {
          format: formatOf(created.parts),
          part_count: created.parts.length,
          // Never typed since ADR 0015; kept so the event's history reads the same.
          source: 'final',
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
        const usedUp = errorAllowanceUsedUp(e);
        if (usedUp) {
          track('allowance_used_up', { ran_out: usedUp.ranOut });
          setAllowanceUsedUp(usedUp);
          return { kind: 'refused' };
        }
        setError(
          errorMessage(
            e,
            request.postNow
              ? "Couldn't post to X. Try again."
              : "Couldn't schedule the post. Try again.",
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

  return { sending, error, allowanceUsedUp, create };
}
