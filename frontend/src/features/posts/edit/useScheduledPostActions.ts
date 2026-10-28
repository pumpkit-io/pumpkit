import { useCallback, useState } from 'react';
import { useGoToChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { pastCommunitiesChanged } from '@/features/scheduledPosts/usePastCommunities';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import {
  scheduledPostService,
  type ScheduledPost,
  type ScheduledPostChanges,
} from '@/services/scheduledPostService';

/** The `source` of `billing_choose_plan_opened` from editing a Scheduled post. */
export const EDIT_BILLING_SOURCE = 'scheduled_post_edit';

/**
 * Saves or unschedules a waiting Scheduled post. A refusal sets `error`; a User no longer
 * Subscribed goes to Choose a Plan.
 */
export function useScheduledPostActions(scheduledPost: ScheduledPost) {
  const { refresh: refreshSubscribed } = useSubscribed();
  const { reload: reloadXConnection } = useXConnectionContext();
  const goToChoosePlan = useGoToChoosePlan();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { id } = scheduledPost;

  const refused = useCallback(
    (e: unknown, fallback: string) => {
      if (errorStatus(e) === 403) {
        refreshSubscribed();
        goToChoosePlan(EDIT_BILLING_SOURCE);
        return;
      }
      setError(errorMessage(e, fallback));
      // The X connection may need reconnecting, which the banner then says.
      if (errorStatus(e) === 409) void reloadXConnection();
    },
    [refreshSubscribed, goToChoosePlan, reloadXConnection],
  );

  /** The saved Scheduled post, or null when it was refused. */
  const save = useCallback(
    async (changes: ScheduledPostChanges): Promise<ScheduledPost | null> => {
      setBusy(true);
      setError(null);
      try {
        const saved = await scheduledPostService.edit(id, changes);
        if (changes.community) pastCommunitiesChanged();
        return saved;
      } catch (e) {
        refused(e, "Couldn't save the changes. Please try again.");
        return null;
      } finally {
        setBusy(false);
      }
    },
    [id, refused],
  );

  /** Whether it was deleted, which makes its Post a Draft again. */
  const unschedule = useCallback(async (): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await scheduledPostService.cancel(id);
      return true;
    } catch (e) {
      refused(e, "Couldn't unschedule it. Please try again.");
      return false;
    } finally {
      setBusy(false);
    }
  }, [id, refused]);

  return { busy, error, save, unschedule };
}
