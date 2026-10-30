import type { ReactNode } from 'react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

/** One provider for a row of labelled buttons, so moving between them skips the delay. */
export function HoverLabels({ children }: { children: ReactNode }) {
  return <TooltipProvider delayDuration={150}>{children}</TooltipProvider>;
}

/** Names an icon button once the pointer rests on it; `quiet` keeps the label shut. */
export function HoverLabel({
  label,
  quiet = false,
  children,
}: {
  label: string;
  quiet?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip open={quiet ? false : undefined}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
