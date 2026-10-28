import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useGoToChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import type { DestinationDraft } from '@/features/scheduledPosts/communities';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import type { ShownPart } from '../shownText';
import { POST_TO_BILLING_SOURCE, type PostToSender } from './postTo';
import { PostToDialog } from './PostToDialog';

/** "Post to…" on a Draft or a Failed Post; a User who isn't Subscribed goes to Choose a Plan. */
export function PostToButton({
  version,
  parts,
  sender,
  initialWhere,
  onDone,
}: {
  version: Version;
  parts: ShownPart[];
  sender: PostToSender;
  initialWhere?: DestinationDraft;
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
      <Button type="button" variant="outline" className="h-10" onClick={start}>
        Post to…
      </Button>
      {open && (
        <PostToDialog
          version={version}
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
