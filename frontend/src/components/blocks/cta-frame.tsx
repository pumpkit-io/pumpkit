import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/** The thin tinted ring the landing page puts around its primary buttons. */
export function CtaFrame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('rounded-[14px] border bg-foreground/10 p-0.5', className)}>{children}</div>
  );
}
