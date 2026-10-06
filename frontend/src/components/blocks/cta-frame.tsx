import type { ReactNode } from 'react';

/** The thin tinted ring the landing page puts around its primary buttons. */
export function CtaFrame({ children }: { children: ReactNode }) {
  return <div className="rounded-[14px] border bg-foreground/10 p-0.5">{children}</div>;
}
