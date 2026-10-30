import type { ReactNode } from 'react';

/** The floating card the dock's status rows sit in, wider than the Post's card. */
export const DOCK_CARD = 'rounded-2xl border border-border bg-card shadow-panel';

/**
 * The card pinned above the Post's card, named for the Post's status. The Post scrolls under it,
 * so its height changes only with the composer's growth and with what `notes` holds, such as an
 * error from the User's send.
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
      <div className="mx-auto w-full max-w-[48rem] space-y-2 px-4 pt-4 sm:px-6 sm:pt-6">
        {children}
        {notes}
      </div>
      {/* The Post scrolling up under the dock fades out instead of stopping at an edge; the fade
          stops short of the scrollbar's 12px so it never veils the thumb. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-0 right-3 top-full h-6 bg-gradient-to-b from-background to-transparent"
      />
    </section>
  );
}
