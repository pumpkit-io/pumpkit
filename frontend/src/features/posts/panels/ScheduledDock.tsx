import { Loader2 } from 'lucide-react';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { DOCK_CARD, Dock } from './Dock';
import { formatWhen } from './panelFacts';
import { DestinationName } from './panelParts';

/**
 * A Scheduled Post takes no Feedback: its text is set to go, and is edited instead, until it is
 * being published. Once it is `posting` it says so, with no Edit, until it is Published or Failed;
 * the Post page announces it, since this dock may mount already posting.
 */
export function ScheduledDock({
  scheduledPost,
  posting,
  notice,
  onEdit,
}: {
  scheduledPost: ScheduledPost;
  posting: boolean;
  /** Under the card, such as why the editor closed. */
  notice: string | null;
  onEdit: () => void;
}) {
  return (
    <Dock name="Scheduled" notes={notice && <LimitNotice message={notice} />}>
      <div className={DOCK_CARD}>
        <div className="flex min-h-10 items-center gap-3 px-4 py-3">
          {posting && (
            <Loader2
              aria-hidden
              className="h-4 w-4 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none"
            />
          )}
          <p className="min-w-0 flex-1 font-sans text-sm text-foreground">
            <span>
              {posting ? 'Posting…' : `Scheduled for ${formatWhen(scheduledPost.publishAt)}`}
            </span>
            {' · '}
            <span>
              <DestinationName scheduledPost={scheduledPost} />
            </span>
          </p>
          {scheduledPost.state === 'scheduled' && !posting && (
            <Button type="button" variant="outline" className="h-10 shrink-0" onClick={onEdit}>
              Edit
            </Button>
          )}
        </div>
      </div>
    </Dock>
  );
}
