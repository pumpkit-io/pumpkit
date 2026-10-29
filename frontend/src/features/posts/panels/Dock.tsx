import type { ReactNode } from 'react';

/**
 * The bar pinned under the Post's card, named for the Post's status. Its height changes only
 * with the composer's growth and with what `above` holds, such as an error from the User's send.
 */
export function Dock({
  name,
  above,
  origin,
  tools,
  children,
}: {
  name: string;
  above?: ReactNode;
  /** The one line saying where the Text came from. */
  origin: ReactNode;
  /** At the right of the origin line. */
  tools?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={name} className="shrink-0 border-t border-border bg-background">
      <div className="mx-auto w-full max-w-[42rem] space-y-2 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 sm:px-6">
        {above}
        <div className="flex h-6 min-w-0 items-center gap-2">
          <div aria-live="polite" className="min-w-0 flex-1">
            {origin}
          </div>
          {tools}
        </div>
        {children}
      </div>
    </section>
  );
}
