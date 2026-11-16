import { ChevronRight, TriangleAlert } from 'lucide-react';
import { useId, useState } from 'react';
import { cn } from '@/lib/utils';
import type { ReachWarning } from '@/services/postService';

const LINE = 'flex items-start gap-1.5 font-sans text-xs text-muted-foreground';

function Icon() {
  return <TriangleAlert aria-hidden className="mt-px h-3.5 w-3.5 shrink-0 text-warning" />;
}

function Lines({ warnings, id }: { warnings: ReachWarning[]; id?: string }) {
  return (
    <ul id={id} className="space-y-1">
      {warnings.map((warning) => (
        <li key={`${warning.code}-${warning.part ?? ''}`} className={LINE}>
          <Icon />
          <span>{warning.message}</span>
        </li>
      ))}
    </ul>
  );
}

/** Every Reach warning in full, one line each, as "Post to…" lists them; nothing for none. */
export function ReachWarningList({ warnings }: { warnings: ReachWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <div role="group" aria-label="Reach warnings">
      <Lines warnings={warnings} />
    </div>
  );
}

/**
 * The Reach warnings under a dock: one as its line, several folded into "N reach warnings",
 * nothing for none. They never stop the User.
 */
export function ReachWarnings({ warnings }: { warnings: ReachWarning[] }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (warnings.length === 0) return null;
  if (warnings.length === 1)
    return (
      <div role="group" aria-label="Reach warnings">
        <p className={LINE}>
          <Icon />
          <span>{warnings[0]!.message}</span>
        </p>
      </div>
    );
  return (
    <div role="group" aria-label="Reach warnings" className="space-y-1.5">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((was) => !was)}
        className={cn(
          LINE,
          'items-center rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        )}
      >
        <Icon />
        <span>{`${warnings.length} reach warnings`}</span>
        <ChevronRight
          aria-hidden
          className={cn(
            'h-3.5 w-3.5 transition-transform motion-reduce:transition-none',
            open && 'rotate-90',
          )}
        />
      </button>
      {open && <Lines warnings={warnings} id={listId} />}
    </div>
  );
}
