import { useCallback, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useGoToChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useCreateScheduledPost } from '@/features/scheduledPosts/useCreateScheduledPost';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import type { ShownPart } from '../shownText';
import { POST_TO_BILLING_SOURCE, type PostToChoice, type PostToSender } from './postTo';
import { PostToDialog } from './PostToDialog';

/** Sends a Draft's Version as its new Scheduled post. */
function useCreateFromVersion(versionId: string): PostToSender {
  const { sending, error, create } = useCreateScheduledPost();
  const send = useCallback(
    ({ destination, when }: PostToChoice) =>
      create({ sourceVersionId: versionId, destination, ...when }),
    [create, versionId],
  );
  return { sending, error, send };
}

/** "Post to…" on a Draft; a User who isn't Subscribed goes to Choose a Plan instead. */
export function PostToButton({
  version,
  parts,
  onDone,
}: {
  version: Version;
  parts: ShownPart[];
  onDone: (scheduledPost: ScheduledPost) => void;
}) {
  const { subscribed } = useSubscribed();
  const goToChoosePlan = useGoToChoosePlan();
  const sender = useCreateFromVersion(version.id);
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
