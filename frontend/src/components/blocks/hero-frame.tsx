import type { ReactNode } from 'react';

/** The bordered 16:9 frame on the hero's right that holds the product media. */
export function HeroFrame({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-2xl border bg-background p-2 shadow-panel">
      <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-muted">
        {children}
      </div>
    </div>
  );
}
