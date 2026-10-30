import type { ReactNode } from 'react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

/** How long a pointer rests on a Post card button before its label shows. */
export const HOVER_LABEL_DELAY_MS = 150;

/** Names an icon button of the Post card in a small label, once the pointer rests on it. */
export function HoverLabel({ label, children }: { label: string; children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={HOVER_LABEL_DELAY_MS}>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
