import { Button } from '@/components/ui/button';
import { useGoToChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { TIME_ZONE } from '@/features/scheduledPosts/localTime';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { EDIT_BILLING_SOURCE } from '../edit/useScheduledPostActions';
import { formatWhen } from './panelFacts';
import { DestinationName, Facts, Panel } from './panelParts';

/**
 * A Scheduled Post takes no Feedback: its text is set to go, and is edited instead, until it is
 * being published.
 */
export function ScheduledPanel({
  scheduledPost,
  shownText,
  onEdit,
}: {
  scheduledPost: ScheduledPost;
  shownText: string;
  onEdit: () => void;
}) {
  const { subscribed } = useSubscribed();
  const goToChoosePlan = useGoToChoosePlan();
  const edit = () => {
    if (subscribed === false) goToChoosePlan(EDIT_BILLING_SOURCE);
    else onEdit();
  };

  return (
    <Panel name="Scheduled">
      <div className="space-y-1">
        <p className="font-sans text-base font-semibold text-foreground">
          Scheduled for {formatWhen(scheduledPost.publishAt)}
        </p>
        <Facts
          items={[<DestinationName key="destination" scheduledPost={scheduledPost} />, TIME_ZONE]}
        />
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <CopyPostButton text={shownText} />
        {scheduledPost.state === 'scheduled' && (
          <Button type="button" variant="outline" className="h-10" onClick={edit}>
            Edit
          </Button>
        )}
      </div>
    </Panel>
  );
}
