import { useEffect, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';

const COPIED_MS = 2000;

/** Copy as an icon: a check for two seconds once copied, and a way out when the browser refuses. */
export function CopyTextButton({ text, disabled = false }: { text: string; disabled?: boolean }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (state !== 'copied') return;
    const timer = window.setTimeout(() => setState('idle'), COPIED_MS);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
      track('post_final_copied');
    } catch {
      setState('failed');
    }
  };

  const Icon = state === 'copied' ? Check : Copy;
  return (
    <TooltipProvider>
      <Tooltip
        open={state === 'failed'}
        onOpenChange={(open) => {
          if (!open) setState('idle');
        }}
      >
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="Copy post"
            disabled={disabled}
            onClick={() => void copy()}
            className={cn(
              'inline-flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-[var(--hover)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 motion-reduce:transition-none',
              state === 'copied' ? 'text-success' : 'text-muted-foreground',
            )}
          >
            <Icon className="h-4 w-4" aria-hidden />
          </button>
        </TooltipTrigger>
        <TooltipContent side="left" className="max-w-56 text-[13px]">
          Couldn&apos;t copy. Select the text and copy it yourself.
        </TooltipContent>
      </Tooltip>
      <span role="status" className="sr-only">
        {state === 'copied' ? 'Copied' : ''}
      </span>
    </TooltipProvider>
  );
}
