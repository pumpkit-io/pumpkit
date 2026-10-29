import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { PostDetail, Version } from '@/services/postService';
import { showsScheduledPost, STATUS_LABEL } from './postStatus';

const DOT_COLOUR = {
  scheduled: 'bg-primary',
  failed: 'bg-destructive',
  published: 'bg-success',
} as const;

type Mark = keyof typeof DOT_COLOUR;

/** The Post's status, on the Version its Text came from only. */
function markOf(version: Version, post: PostDetail): Mark | null {
  if (!showsScheduledPost(post, version)) return null;
  return post.status === 'draft' ? null : post.status;
}

const STEP =
  'inline-flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40';

/**
 * Steps through every Version. The one the Text came from gets a dot in its Scheduled post's
 * colour, and the footer says what made the Version shown: its Feedback, or the Brief.
 */
export function VersionPager({
  post,
  index,
  onChange,
}: {
  post: PostDetail;
  index: number;
  onChange: (index: number) => void;
}) {
  const { versions } = post;
  const shown = versions[index];
  if (!shown) return null;
  const shownMark = markOf(shown, post);
  const origin = shown.feedback === null ? 'From your brief' : `"${shown.feedback}"`;

  return (
    <nav aria-label="Versions" className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          className={STEP}
          aria-label="Previous Version"
          disabled={index === 0}
          onClick={() => onChange(index - 1)}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
        </button>
        <div className="flex min-w-0 flex-col items-center gap-1.5">
          <ol className="flex flex-wrap items-center justify-center gap-0.5">
            {versions.map((version, i) => {
              const state = markOf(version, post);
              const label = state
                ? `Version ${version.number}, ${STATUS_LABEL[state]}`
                : `Version ${version.number}`;
              return (
                <li key={version.id}>
                  <button
                    type="button"
                    aria-label={label}
                    aria-current={i === index ? 'true' : undefined}
                    onClick={() => onChange(i)}
                    className="flex h-6 w-6 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span
                      aria-hidden
                      className={cn(
                        'block rounded-full transition-all motion-reduce:transition-none',
                        state ? DOT_COLOUR[state] : 'bg-muted-foreground/40',
                        i === index
                          ? 'h-2.5 w-2.5 ring-2 ring-foreground/30 ring-offset-1 ring-offset-background'
                          : 'h-2 w-2',
                      )}
                    />
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="font-mono text-xs tabular-nums text-muted-foreground">
            Version {shown.number} of {versions.length}
          </p>
        </div>
        <button
          type="button"
          className={STEP}
          aria-label="Next Version"
          disabled={index === versions.length - 1}
          onClick={() => onChange(index + 1)}
        >
          <ChevronRight className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <p className="break-words text-center font-sans text-sm text-muted-foreground">
        {shownMark ? `${STATUS_LABEL[shownMark]} · ${origin}` : origin}
      </p>
    </nav>
  );
}
