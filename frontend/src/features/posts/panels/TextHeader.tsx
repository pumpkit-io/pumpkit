import type { ReactNode } from 'react';

/** The Post card's top row: where the Text came from, and at its right the Text's tools. */
export function TextHeader({ origin, tools }: { origin: ReactNode; tools?: ReactNode }) {
  return (
    <div className="flex h-11 min-w-0 items-center gap-2 border-b border-border pl-4 pr-2 sm:pl-5">
      <div aria-live="polite" className="min-w-0 flex-1">
        {origin}
      </div>
      {tools}
    </div>
  );
}

/** The Post card's bottom row, with its action at the right, such as "Post to…". */
export function TextFooter({ children }: { children: ReactNode }) {
  return (
    <div className="flex justify-end border-t border-border px-4 py-3 sm:px-5">{children}</div>
  );
}
