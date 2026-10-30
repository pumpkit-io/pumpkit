import { useLayoutEffect, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import type { PostCounts } from '@/services/postService';
import { STATUS_TAB, TAB_ORDER } from '../postStatus';

type Indicator = { left: number; width: number; animate: boolean };

/** One link per status, each to its own address, with its count once known. */
export function PostsTabs({ counts }: { counts: PostCounts | null }) {
  const { pathname } = useLocation();
  const listRef = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState<Indicator | null>(null);

  useLayoutEffect(() => {
    const list = listRef.current;
    const active = list?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!list || !active) return setIndicator(null);
    const measure = () =>
      // The first placement snaps, so the line doesn't slide in from the left on page load.
      setIndicator((prev) => ({
        left: active.offsetLeft,
        width: active.offsetWidth,
        animate: prev !== null,
      }));
    measure();
    // Counts arrive after the first paint and change each tab's width.
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    return () => observer.disconnect();
  }, [pathname]);

  return (
    <nav aria-label="Posts by status" className="overflow-x-auto overflow-y-hidden">
      <div ref={listRef} className="relative flex w-max min-w-full gap-6">
        <span aria-hidden className="absolute inset-x-0 bottom-0 h-px bg-border" />
        {TAB_ORDER.map((status) => {
          const { label, path, icon: Icon } = STATUS_TAB[status];
          const count = counts?.[status];
          return (
            <NavLink
              key={status}
              to={path}
              className={cn(
                'inline-flex h-10 shrink-0 items-center gap-2 px-3 font-sans text-sm text-muted-foreground transition-colors',
                'hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                'aria-[current=page]:font-medium aria-[current=page]:text-foreground',
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
        {indicator && (
          <span
            aria-hidden
            className={cn(
              'absolute bottom-0 left-0 h-0.5 bg-primary',
              indicator.animate &&
                'transition-[transform,width] duration-300 ease-out motion-reduce:transition-none',
            )}
            style={{ width: indicator.width, transform: `translateX(${indicator.left}px)` }}
          />
        )}
      </div>
    </nav>
  );
}
