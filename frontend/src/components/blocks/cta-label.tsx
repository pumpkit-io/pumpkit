import type { ReactNode } from 'react';

export function CtaLabel({ children, pending }: { children: ReactNode; pending: boolean }) {
  return (
    <span aria-hidden={pending || undefined} className={pending ? 'invisible' : undefined}>
      {children ?? 'Get started'}
    </span>
  );
}
