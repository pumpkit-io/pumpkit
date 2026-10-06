import { useId } from 'react';
import type { Tell } from '@/services/postService';

/** What the slop check found in a Final; the User decides whether any of it needs Feedback. */
export function SlopTells({ tells }: { tells: Tell[] }) {
  const headingId = useId();

  if (tells.length === 0) {
    return (
      <p className="border-t border-border pt-3 font-sans text-xs text-muted-foreground">
        No machine-written tells found.
      </p>
    );
  }

  return (
    <div className="space-y-2 border-t border-border pt-3">
      <h4 id={headingId} className="font-sans text-xs font-semibold text-foreground">
        Machine-written tells
      </h4>
      <ul aria-labelledby={headingId} className="flex flex-wrap gap-1.5">
        {tells.map((tell) => (
          <li
            key={tell.name}
            className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 font-sans text-xs text-amber-700 dark:text-amber-300"
          >
            {tell.description}
          </li>
        ))}
      </ul>
    </div>
  );
}
