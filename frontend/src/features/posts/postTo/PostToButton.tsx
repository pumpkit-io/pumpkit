import { useState } from 'react';
import { Loader2 } from 'lucide-react';
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
  prepare,
  onDone,
}: {
  /** The Text's Format. */
  format: Format;
  parts: ShownPart[];
  sender: PostToSender;
  initialWhere?: DestinationDraft;
  disabled?: boolean;
  /** Runs before the dialog opens, such as saving the User's last edit; false keeps it shut. */
  prepare?: () => Promise<boolean>;
  onDone: (scheduledPost: ScheduledPost) => void;
}) {
  const { subscribed } = useSubscribed();
  const goToChoosePlan = useGoToChoosePlan();
  const [open, setOpen] = useState(false);
  const [preparing, setPreparing] = useState(false);

  const start = async () => {
    if (subscribed === false) {
      goToChoosePlan(POST_TO_BILLING_SOURCE);
      return;
    }
    if (prepare) {
      setPreparing(true);
      const ready = await prepare();
      setPreparing(false);
      if (!ready) return;
    }
    setOpen(true);
  };

  return (
    <>
      <Button
        type="button"
        variant="solid"
        className="h-10 shrink-0 rounded-full"
        disabled={disabled || preparing}
        aria-busy={preparing}
        onClick={() => void start()}
      >
        {preparing && (
          <Loader2 aria-hidden className="h-4 w-4 animate-spin motion-reduce:animate-none" />
        )}
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
