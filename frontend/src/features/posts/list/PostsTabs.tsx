import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';
import type { PostCounts, PostStatus } from '@/services/postService';
import { STATUS_TAB } from '../postStatus';

/** The tabs in the order they sit, Scheduled first: what goes out next is what to check. */
export const TAB_ORDER: PostStatus[] = ['scheduled', 'draft', 'published', 'failed'];

/** How each tab orders its Posts, as the line under the tabs says it. */
export const TAB_ORDER_LINE: Record<PostStatus, string> = {
  scheduled: 'Next to go out first.',
  draft: 'Newest Version first.',
  published: 'Most recently published first.',
  failed: 'Most recently due first.',
};

/** One link per status, each to its own address, with its count once known. */
export function PostsTabs({ counts }: { counts: PostCounts | null }) {
  return (
    <nav aria-label="Posts by status" className="flex gap-1 overflow-x-auto border-b border-border">
      {TAB_ORDER.map((status) => {
        const { label, path } = STATUS_TAB[status];
        const count = counts?.[status];
        return (
          <NavLink
            key={status}
            to={path}
            className={cn(
              '-mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 border-transparent px-3 font-sans text-sm text-muted-foreground',
              'hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              'aria-[current=page]:border-primary aria-[current=page]:font-medium aria-[current=page]:text-foreground',
            )}
          >
            {label}{' '}
            {count !== undefined && (
              <span
                className={cn(
                  'rounded-md px-1.5 font-mono text-xs tabular-nums',
                  status === 'failed' && count > 0
                    ? 'bg-destructive/15 text-destructive'
                    : 'bg-muted text-muted-foreground',
                )}
              >
                {count}
              </span>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}
