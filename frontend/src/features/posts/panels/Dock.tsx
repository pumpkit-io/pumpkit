import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { COMPOSER_COLUMN } from '../Composer';

/** The floating card the dock's status rows sit in, wider than the Post's card. */
export const DOCK_CARD = 'rounded-2xl border border-border bg-card shadow-panel';

/**
 * The card pinned above the Post's card, named for the Post's status. It takes the height it
 * needs, which changes with the composer's growth and with what `notes` holds, such as an error
 * from the User's send; the Post's card gets the rest.
 */
export function Dock({
  name,
  notes,
  children,
}: {
  name: string;
  /** Under the card, such as why a send failed. */
  notes?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={name} className="relative z-10 shrink-0 bg-background">
      <div className={cn(COMPOSER_COLUMN, 'space-y-2 pt-4 sm:pt-6')}>
        {children}
        {notes}
      </div>
    </section>
  );
}
