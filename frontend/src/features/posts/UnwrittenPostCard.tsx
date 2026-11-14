import { Button } from '@/components/ui/button';
import type { UnwrittenPost } from '@/services/postService';
import { OriginLine } from './panels/OriginLine';

// The lines a written post would fill, widest first, as the loading placeholder draws them.
const LINES = ['w-full', 'w-4/5', 'w-3/5'];

/**
 * A Post before its first Version: the card Pumpkit is writing, with its lines filling in, or
 * the one it couldn't write, with Retry (ADR 0026). Reduced motion keeps the lines still.
 */
export function UnwrittenPostCard({
  post,
  retrying,
  onRetry,
}: {
  post: UnwrittenPost;
  retrying: boolean;
  onRetry: () => void;
}) {
  const writing = post.writingState === 'writing';
  return (
    <div className="space-y-3">
      <OriginLine brief={post.brief} plan={post.plan} edited={false} />
      <div className="flex gap-3 rounded-xl border border-border bg-card px-4 py-4 sm:px-5">
        <div aria-hidden className="h-10 w-10 shrink-0 rounded-full bg-muted" />
        {writing ? (
          <div role="status" className="flex-1 space-y-3 pt-1">
            <p className="font-sans text-[15px] text-foreground">Writing…</p>
            <div aria-hidden className="space-y-3">
              {LINES.map((width, index) => (
                <div key={width} className={`h-3 overflow-hidden rounded-full bg-muted ${width}`}>
                  <div
                    className="post-writing-line h-full rounded-full bg-primary/20"
                    style={{ animationDelay: `${index * 0.4}s` }}
                  />
                </div>
              ))}
            </div>
            <p className="font-sans text-[13px] text-muted-foreground">
              This takes about a minute. You can leave this page and come back.
            </p>
          </div>
        ) : (
          <div className="flex-1 space-y-3 pt-1">
            <p role="alert" className="font-sans text-[15px] text-foreground">
              This post couldn&apos;t be written.
            </p>
            <p className="font-sans text-[13px] text-muted-foreground">
              Retry writes it again from the same plan. A generation is used only once it&apos;s
              written.
            </p>
            <Button
              type="button"
              variant="solid"
              className="h-10"
              disabled={retrying}
              onClick={onRetry}
            >
              {retrying ? 'Retrying…' : 'Retry'}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
