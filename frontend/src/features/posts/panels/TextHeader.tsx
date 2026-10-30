import type { ReactNode } from 'react';

/**
 * The Post card's top row: where the Text came from, then the Text's tools and, last, its
 * action, such as "Post to…". On a narrow screen the tools and the action wrap under the origin.
 */
export function TextHeader({
  origin,
  tools,
  action,
}: {
  origin: ReactNode;
  tools?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-16 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border py-3 pl-4 pr-3 sm:pl-5">
      <div aria-live="polite" className="min-w-0 flex-1 basis-56">
        {origin}
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-3">
        {tools}
        {action && (
          <>
            <span aria-hidden className="h-6 w-px bg-border" />
            {action}
          </>
        )}
      </div>
    </div>
  );
}
