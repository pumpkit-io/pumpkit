import { useCallback, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useCreateScheduledPost } from '@/features/scheduledPosts/useCreateScheduledPost';
import { pastCommunitiesChanged } from '@/features/scheduledPosts/usePastCommunities';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';
import type { PostToChoice, PostToSender } from './postTo';

/** Sends a Draft's Version as its new Scheduled post. */
export function useCreateFromVersion(versionId: string): PostToSender {
  const { sending, error, create } = useCreateScheduledPost();
  const send = useCallback(
    ({ destination, when }: PostToChoice) =>
      create({ sourceVersionId: versionId, destination, ...when }),
    [create, versionId],
  );
  return { sending, error, send };
}

/**
 * Reschedules or posts now a Failed Post's one Scheduled post, with the Version on screen. The
 * Version it came from is sent as it stands, so text edited after scheduling is kept.
 */
export function useRetryFailed(scheduledPost: ScheduledPost, versionId: string): PostToSender {
  const { refresh: refreshSubscribed } = useSubscribed();
  const { reload: reloadXConnection } = useXConnectionContext();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { id, sourceVersionId } = scheduledPost;

  const send = useCallback(
    async ({ destination, when }: PostToChoice) => {
      setSending(true);
      setError(null);
      try {
        const retried = await scheduledPostService.edit(id, {
          ...(versionId !== sourceVersionId && { sourceVersionId: versionId }),
          community: destination.community,
          shareWithFollowers: destination.shareWithFollowers,
          ...(when.postNow ? { publishNow: true } : { publishAt: when.publishAt }),
        });
        if (destination.community) pastCommunitiesChanged();
        // Failing again may have flagged the X connection for reconnecting.
        if (retried.state === 'failed') void reloadXConnection();
        return { kind: 'created', scheduledPost: retried } as const;
      } catch (e) {
        if (errorStatus(e) === 403) {
          refreshSubscribed();
          return { kind: 'notSubscribed' } as const;
        }
        setError(
          errorMessage(
            e,
            when.postNow
              ? "Couldn't post to X. Please try again."
              : "Couldn't schedule the post. Please try again.",
          ),
        );
        if (errorStatus(e) === 409) void reloadXConnection();
        return { kind: 'refused' } as const;
      } finally {
        setSending(false);
      }
    },
    [id, sourceVersionId, versionId, refreshSubscribed, reloadXConnection],
  );

  return { sending, error, send };
}
