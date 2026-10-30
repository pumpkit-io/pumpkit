import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';
import type { PostCounts } from '@/services/postService';
import { STATUS_TAB, TAB_ORDER } from '../postStatus';

/** One link per status, each to its own address, with its count once known. */
export function PostsTabs({ counts }: { counts: PostCounts | null }) {
  return (
    <nav aria-label="Posts by status" className="flex gap-1 overflow-x-auto border-b border-border">
      {TAB_ORDER.map((status) => {
        const { label, path, icon: Icon } = STATUS_TAB[status];
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
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
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
