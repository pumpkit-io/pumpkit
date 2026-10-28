import { useState } from 'react';
import { cn } from '@/lib/utils';

/** The Brief above the Version, cut to one line on a phone so the Version stays on screen. */
export function BriefBlock({ brief }: { brief: string }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="Brief" className="space-y-1 border-l-2 border-primary/50 pl-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-sans text-xs font-medium text-muted-foreground">Your Brief</p>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="font-sans text-xs font-medium text-muted-foreground underline underline-offset-2 hover:text-foreground sm:hidden"
        >
          {open ? 'Show less' : 'Show all'}
        </button>
      </div>
      <p
        className={cn(
          'break-words font-sans text-sm text-muted-foreground',
          open
            ? 'whitespace-pre-wrap'
            : 'truncate sm:max-h-40 sm:overflow-y-auto sm:whitespace-pre-wrap sm:[text-overflow:clip]',
        )}
      >
        {brief}
      </p>
    </section>
  );
}
