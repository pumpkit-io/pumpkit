import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/** How many Parts a Thread has, shown above it so its Format reads at a glance. */
export function ThreadSize({ count }: { count: number }) {
  return (
    <p className="font-sans text-xs font-medium text-muted-foreground">Thread, {count} Parts</p>
  );
}

/** A Thread's Parts, each under its number as X will thread them. */
export function ThreadParts<T>({
  parts,
  className,
  aside,
  children,
}: {
  parts: T[];
  className?: string;
  /** Beside each Part's number, such as a button acting on that Part. */
  aside?: (part: T, number: number) => ReactNode;
  children: (part: T, number: number) => ReactNode;
}) {
  return (
    <ol aria-label="Parts" className={cn('space-y-3', className)}>
      {parts.map((part, index) => {
        const number = index + 1;
        return (
          <li
            key={index}
            aria-label={`Part ${number}`}
            className="space-y-2 border-l-2 border-border pl-3"
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-sans text-xs font-medium tabular-nums text-muted-foreground">
                Part {number}
              </p>
              {aside?.(part, number)}
            </div>
            {children(part, number)}
          </li>
        );
      })}
    </ol>
  );
}
