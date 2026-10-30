import { Button } from '@/components/ui/button';
import { useGoToChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { EDIT_BILLING_SOURCE } from '../edit/useScheduledPostActions';
import { DOCK_CARD, Dock } from './Dock';
import { formatWhen } from './panelFacts';
import { DestinationName } from './panelParts';

/**
 * A Scheduled Post takes no Feedback: its text is set to go, and is edited instead, until it is
 * being published.
 */
export function ScheduledDock({
  scheduledPost,
  onEdit,
}: {
  scheduledPost: ScheduledPost;
  onEdit: () => void;
}) {
  const { subscribed } = useSubscribed();
  const goToChoosePlan = useGoToChoosePlan();

  const edit = () => {
    if (subscribed === false) goToChoosePlan(EDIT_BILLING_SOURCE);
    else onEdit();
  };

  return (
    <Dock name="Scheduled">
      <div className={DOCK_CARD}>
        <div className="flex min-h-10 items-center gap-3 px-4 py-3">
          <p className="min-w-0 flex-1 font-sans text-sm text-foreground">
            <span>Scheduled for {formatWhen(scheduledPost.publishAt)}</span>
            {' · '}
            <span>
              <DestinationName scheduledPost={scheduledPost} />
            </span>
          </p>
          {scheduledPost.state === 'scheduled' && (
            <Button type="button" variant="outline" className="h-10 shrink-0" onClick={edit}>
              Edit
            </Button>
          )}
        </div>
      </div>
    </Dock>
  );
}
