import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { HoverLabel, HoverLabels } from '@/features/posts/HoverLabel';
import type { DestinationDraft } from '@/features/scheduledPosts/communities';
import { cn } from '@/lib/utils';
import type { Format } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import type { ShownPart } from '../shownText';
import type { PostToSender } from './postTo';
import { PostToDialog } from './PostToDialog';

/** "Post to…" on a Draft or a Failed Post. */
export function PostToButton({
  format,
  parts,
  sender,
  initialWhere,
  disabled = false,
  waitingFor = null,
  prepare,
  onDone,
}: {
  /** The Text's Format. */
  format: Format;
  parts: ShownPart[];
  sender: PostToSender;
  initialWhere?: DestinationDraft;
  disabled?: boolean;
  /** Why it waits before opening, such as an upload in flight; it stays focusable to say so. */
  waitingFor?: string | null;
  /** Runs before the dialog opens, such as saving the User's last edit; false keeps it shut. */
  prepare?: () => Promise<boolean>;
  onDone: (scheduledPost: ScheduledPost) => void;
}) {
  const [open, setOpen] = useState(false);
  const [preparing, setPreparing] = useState(false);

  const start = async () => {
    if (waitingFor) return;
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
      <HoverLabels>
        <HoverLabel label={waitingFor ?? ''} quiet={!waitingFor}>
          <Button
            type="button"
            variant="solid"
            className={cn('h-10 shrink-0', waitingFor && 'cursor-not-allowed opacity-50')}
            disabled={disabled || preparing}
            aria-disabled={waitingFor ? true : undefined}
            aria-busy={preparing}
            onClick={() => void start()}
          >
            {preparing && (
              <Loader2 aria-hidden className="h-4 w-4 animate-spin motion-reduce:animate-none" />
            )}
            Post to…
          </Button>
        </HoverLabel>
      </HoverLabels>
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
