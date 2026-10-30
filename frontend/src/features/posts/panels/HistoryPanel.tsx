import { useId, useState } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { ChevronDown, History, X } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useGoToChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { shortTimeAgo } from '@/lib/relativeTime';
import { PHONE, useMediaQuery } from '@/lib/useMediaQuery';
import { cn } from '@/lib/utils';
import type { Version } from '@/services/postService';
import { HoverLabel } from '@/features/posts/HoverLabel';
import { ICON_BUTTON } from './iconButton';

const HISTORY_BILLING_SOURCE = 'post_history_restore';

interface HistoryProps {
  brief: string;
  versions: Version[];
  /** The Version the Text came from, and whether it was edited since. */
  textVersionNumber: number;
  edited: boolean;
  /** Left out where the Text can't change: History is then read-only. */
  onRestore?: (versionNumber: number) => void;
}

function firstLine(text: string): string {
  return (text.split('\n').find((line) => line.trim()) ?? '').replace(/\s+/g, ' ').trim();
}

function HistoryRow({
  version,
  brief,
  onScreen,
  edited,
  onPick,
}: {
  version: Version;
  brief: string;
  onScreen: boolean;
  edited: boolean;
  onPick?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const fullId = useId();
  const kind = version.feedback ? 'Feedback' : 'Brief';
  const asked = version.feedback ?? brief;

  const summary = (
    <>
      <span className="flex items-baseline justify-between gap-3">
        <span className="font-medium text-foreground">Version {version.number}</span>
        {onScreen ? (
          <span className="flex shrink-0 items-center gap-1.5 text-foreground">
            <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />
            {edited ? 'Edited on screen' : 'On screen'}
          </span>
        ) : (
          <span className="shrink-0">{shortTimeAgo(version.createdAt)}</span>
        )}
      </span>
      <span className="block truncate">
        {kind}: “{firstLine(asked)}”
      </span>
    </>
  );

  const rowText = 'min-w-0 flex-1 rounded-lg px-2.5 py-2 text-left';
  return (
    <li className={cn('rounded-lg', onScreen && 'bg-[var(--hover)]')}>
      <div className="flex items-start gap-0.5">
        {onPick ? (
          <button
            type="button"
            aria-current={onScreen ? 'true' : undefined}
            onClick={onPick}
            className={cn(
              rowText,
              'transition-colors hover:bg-[var(--hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none',
            )}
          >
            {summary}
          </button>
        ) : (
          <div className={rowText}>{summary}</div>
        )}
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={fullId}
          aria-label={`Show the full ${kind.toLowerCase()} of version ${version.number}`}
          onClick={() => setExpanded((open) => !open)}
          className={cn(ICON_BUTTON, 'mt-1.5 shrink-0')}
        >
          <ChevronDown
            aria-hidden
            className={cn(
              'h-4 w-4 transition-transform motion-reduce:transition-none',
              expanded && 'rotate-180',
            )}
          />
        </button>
      </div>
      {expanded && (
        <p
          id={fullId}
          className="whitespace-pre-wrap break-words px-2.5 pb-2.5 text-sm leading-6 text-foreground"
        >
          {asked}
        </p>
      )}
    </li>
  );
}

function HistoryList({
  brief,
  versions,
  textVersionNumber,
  edited,
  onPick,
}: Omit<HistoryProps, 'onRestore'> & { onPick?: (version: Version) => void }) {
  return (
    <ul className="space-y-0.5 font-sans text-[13px] tabular-nums text-muted-foreground">
      {[...versions].reverse().map((version) => (
        <HistoryRow
          key={version.id}
          version={version}
          brief={brief}
          onScreen={version.number === textVersionNumber}
          edited={edited}
          onPick={onPick && (() => onPick(version))}
        />
      ))}
    </ul>
  );
}

/**
 * The Post card's History button: every Version, newest first, in a popover below it, or a bottom
 * sheet on a phone. Clicking one restores it, unless it is already the Text as written.
 */
export function HistoryButton({ onRestore, ...list }: HistoryProps) {
  const phone = useMediaQuery(PHONE);
  const [open, setOpen] = useState(false);
  // Closing hands focus back to the button, which would otherwise open its label until it blurs.
  const [labelQuiet, setLabelQuiet] = useState(false);
  const openChange = (next: boolean) => {
    setOpen(next);
    if (!next) setLabelQuiet(true);
  };
  const { subscribed } = useSubscribed();
  const goToChoosePlan = useGoToChoosePlan();

  const pick = (version: Version) => {
    openChange(false);
    if (version.number === list.textVersionNumber && !list.edited) return;
    if (subscribed === false) goToChoosePlan(HISTORY_BILLING_SOURCE);
    else onRestore?.(version.number);
  };
  const historyList = <HistoryList {...list} onPick={onRestore && pick} />;
  const trigger = (
    <button
      type="button"
      aria-label="History"
      onPointerLeave={() => setLabelQuiet(false)}
      onBlur={() => setLabelQuiet(false)}
      className={cn(ICON_BUTTON, '-my-1')}
    >
      <History aria-hidden className="h-4 w-4" />
    </button>
  );

  if (phone) {
    return (
      <DialogPrimitive.Root open={open} onOpenChange={openChange}>
        <HoverLabel label="Versions history" quiet={open || labelQuiet}>
          <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>
        </HoverLabel>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 motion-reduce:animate-none" />
          <DialogPrimitive.Content
            aria-describedby={undefined}
            className="fixed inset-x-0 bottom-0 z-50 flex max-h-[80vh] flex-col rounded-t-2xl border-t border-border bg-popover px-2 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2 text-popover-foreground shadow-xl focus:outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom motion-reduce:animate-none"
          >
            <div className="flex items-center justify-between px-2.5 py-1">
              <DialogPrimitive.Title className="font-sans text-sm font-medium text-foreground">
                History
              </DialogPrimitive.Title>
              <DialogPrimitive.Close aria-label="Close" className={ICON_BUTTON}>
                <X aria-hidden className="h-4 w-4" />
              </DialogPrimitive.Close>
            </div>
            <div className="overflow-y-auto">{historyList}</div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    );
  }

  return (
    <Popover open={open} onOpenChange={openChange}>
      <HoverLabel label="Versions history" quiet={open || labelQuiet}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      </HoverLabel>
      <PopoverContent
        side="bottom"
        align="end"
        aria-label="History"
        className="max-h-[min(26rem,60vh)] w-[min(26rem,calc(100vw-2rem))] overflow-y-auto p-1.5"
      >
        {historyList}
      </PopoverContent>
    </Popover>
  );
}
