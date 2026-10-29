import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useGoToChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import type { DestinationDraft } from '@/features/scheduledPosts/communities';
import type { Format } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import type { ShownPart } from '../shownText';
import { POST_TO_BILLING_SOURCE, type PostToSender } from './postTo';
import { PostToDialog } from './PostToDialog';

/** "Post to…" on a Draft or a Failed Post; a User who isn't Subscribed goes to Choose a Plan. */
export function PostToButton({
  format,
  parts,
  sender,
  initialWhere,
  disabled = false,
  onDone,
}: {
  /** The Text's Format. */
  format: Format;
  parts: ShownPart[];
  sender: PostToSender;
  initialWhere?: DestinationDraft;
  disabled?: boolean;
  onDone: (scheduledPost: ScheduledPost) => void;
}) {
  const { subscribed } = useSubscribed();
  const goToChoosePlan = useGoToChoosePlan();
  const [open, setOpen] = useState(false);

  const start = () => {
    if (subscribed === false) goToChoosePlan(POST_TO_BILLING_SOURCE);
    else setOpen(true);
  };

  return (
    <>
      <Button
        type="button"
        variant="solid"
        className="h-10 shrink-0 rounded-full"
        disabled={disabled}
        onClick={start}
      >
        Post to…
      </Button>
      {open && (
        <PostToDialog
          format={format}
          parts={parts}
          sender={sender}
          initialWhere={initialWhere}
          onClose={() => setOpen(false)}
          onDone={(scheduledPost) => {
            setOpen(false);
            onDone(scheduledPost);
          }}
        />
      )}
    </>
  );
}
