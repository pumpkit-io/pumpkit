import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useReadWhileWriting } from '@/features/posts/useReadWhileWriting';
import { WRITING_POLL_MAX_MS } from '@/services/postService';
import { briefService, lonePost, type RecentBrief } from '@/services/briefService';

/** How often the list is read again while a Brief is writing; slower than a Brief's own page. */
export const RECENT_BRIEFS_POLL_MS = 10_000;

const recentBriefsDelay = (failures: number) =>
  Math.min(RECENT_BRIEFS_POLL_MS * 2 ** failures, WRITING_POLL_MAX_MS);

/** A Brief's state in one label, by ADR 0025's order. */
export function recentBriefLabel(brief: RecentBrief): string {
  if (brief.postsWriting > 0) return 'Writing…';
  if (brief.postsNotWritten === 1) return "1 post couldn't be written";
  if (brief.postsNotWritten > 1) return `${brief.postsNotWritten} posts couldn't be written`;
  const written = brief.postsWritten;
  if (written === 0) return 'Not written yet';
  if (brief.ideasOffered > 0) return `${written} of ${written + brief.ideasOffered} written`;
  return `${written} written`;
}

/** Where a row opens: the Brief's page, or its Post when the page would open that instead. */
function pathOf(brief: RecentBrief): string {
  const only = lonePost(brief.postIds, brief.ideasOffered);
  return only ? `/posts/${only}` : `/briefs/${brief.id}`;
}

const isWriting = (briefs: RecentBrief[]) => briefs.some((brief) => brief.postsWriting > 0);

/**
 * The User's latest Briefs, read when New post opens and again while any is writing. A list that
 * can't be read is left out, since the composer is what the page is for.
 */
function useRecentBriefs(): RecentBrief[] {
  const [briefs, setBriefs] = useState<RecentBrief[]>([]);
  const { key } = useLocation();
  const read = useCallback(() => briefService.recent(), []);
  const gone = useCallback(() => setBriefs([]), []);

  useEffect(() => {
    let current = true;
    read().then(
      (answer) => {
        if (current) setBriefs(answer);
      },
      () => {},
    );
    return () => {
      current = false;
    };
  }, [read, key]);

  useReadWhileWriting(isWriting(briefs), read, setBriefs, gone, recentBriefsDelay);
  return briefs;
}

/** "Recent briefs" under the composer; not shown while the User has none. */
export function RecentBriefs() {
  const briefs = useRecentBriefs();
  if (briefs.length === 0) return null;
  return (
    <section aria-labelledby="recent-briefs" className="max-w-[68ch] space-y-2 pt-10">
      <h2 id="recent-briefs" className="font-sans text-[13px] font-medium text-foreground">
        Recent briefs
      </h2>
      <ul className="divide-y divide-border border-y border-border">
        {briefs.map((brief) => {
          const label = recentBriefLabel(brief);
          return (
            <li key={brief.id}>
              <Link
                to={pathOf(brief)}
                aria-label={`${brief.textStart}, ${label}`}
                className="group flex min-h-11 items-baseline justify-between gap-4 rounded-sm py-2.5 font-sans focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="min-w-0 truncate text-sm text-foreground underline-offset-2 group-hover:underline">
                  {brief.textStart}
                </span>
                <span className="shrink-0 text-[13px] tabular-nums text-muted-foreground">
                  {label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
