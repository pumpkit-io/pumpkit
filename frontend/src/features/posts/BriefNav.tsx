import type { LucideIcon } from 'lucide-react';
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { PlaceInBrief } from '@/services/postService';

const STEP =
  'inline-flex h-9 w-9 items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function Step({
  postId,
  label,
  icon: Icon,
}: {
  postId: string | null;
  label: string;
  icon: LucideIcon;
}) {
  if (!postId)
    return (
      <a
        role="link"
        aria-disabled="true"
        aria-label={label}
        className={`${STEP} text-muted-foreground/40`}
      >
        <Icon aria-hidden className="h-4 w-4" />
      </a>
    );
  return (
    <Link
      to={`/posts/${postId}`}
      aria-label={label}
      className={`${STEP} text-muted-foreground hover:bg-muted hover:text-foreground`}
    >
      <Icon aria-hidden className="h-4 w-4" />
    </Link>
  );
}

/**
 * "← Posts from your brief   ‹ 2 of 4 ›" above a Post from a Brief with several Posts; nothing on
 * a Post that is its Brief's only one.
 */
export function BriefNav({ briefId, place }: { briefId: string; place: PlaceInBrief }) {
  if (place.postCount < 2) return null;
  return (
    <nav
      aria-label="Posts from your brief"
      className="flex shrink-0 items-center justify-between gap-3 pb-3"
    >
      <Link
        to={`/briefs/${briefId}`}
        className="inline-flex min-w-0 items-center gap-1.5 rounded-sm font-sans text-[13px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="truncate">Posts from your brief</span>
      </Link>
      <div className="-mr-2 flex shrink-0 items-center">
        <Step postId={place.previousPostId} label="Previous post" icon={ChevronLeft} />
        <p className="px-1 font-sans text-[13px] tabular-nums text-muted-foreground">
          <span className="sr-only">Post </span>
          {`${place.position} of ${place.postCount}`}
        </p>
        <Step postId={place.nextPostId} label="Next post" icon={ChevronRight} />
      </div>
    </nav>
  );
}
