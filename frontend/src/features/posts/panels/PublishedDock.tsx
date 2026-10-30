import { Button } from '@/components/ui/button';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { DOCK_CARD, Dock } from './Dock';
import { formatWhen } from './panelFacts';
import { DestinationName } from './panelParts';

/** A Published Post is finished: when and where it went, and the way to it on X. */
export function PublishedDock({ scheduledPost }: { scheduledPost: ScheduledPost }) {
  return (
    <Dock name="Published">
      <div className={DOCK_CARD}>
        <div className="flex min-h-10 items-center gap-3 px-4 py-3">
          <p className="min-w-0 flex-1 font-sans text-sm text-foreground">
            <span>
              Published {formatWhen(scheduledPost.publishedAt ?? scheduledPost.publishAt)}
            </span>
            {' · '}
            <span>
              <DestinationName scheduledPost={scheduledPost} />
            </span>
            {scheduledPost.community && (
              <>
                {' · '}
                <span className="text-muted-foreground">
                  {scheduledPost.shareWithFollowers
                    ? 'Shared with your followers'
                    : 'Not shared with your followers'}
                </span>
              </>
            )}
          </p>
          {scheduledPost.xPostUrl && (
            <Button asChild variant="outline" className="h-10 shrink-0">
              <a href={scheduledPost.xPostUrl} target="_blank" rel="noreferrer">
                View on X
              </a>
            </Button>
          )}
        </div>
      </div>
    </Dock>
  );
}
