import { useEffect, useId, useState, type ReactNode } from 'react';
import { ThreadParts } from '@/components/ThreadParts';
import { Button } from '@/components/ui/button';
import { FinalToXActions } from '@/features/scheduledPosts/FinalToX';
import { track, type EventName } from '@/lib/analytics';
import { formatCount } from '@/lib/characters';
import { cn } from '@/lib/utils';
import { SlopTells } from './SlopTells';
import type { Part, Version } from '@/services/postService';

interface CopyButtonProps {
  text: string;
  event: EventName;
  size?: 'sm' | 'xs';
  /** The button's label until it has copied. */
  children: ReactNode;
}

function CopyButton({ text, event, size = 'sm', children }: CopyButtonProps) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (state !== 'copied') return;
    const timer = window.setTimeout(() => setState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
      track(event);
    } catch {
      setState('failed');
    }
  };

  return (
    <div className="flex items-center gap-3">
      {state === 'failed' && (
        <span className="font-sans text-xs text-muted-foreground">
          Couldn&apos;t copy. Select the text and copy it yourself.
        </span>
      )}
      <Button
        size="sm"
        variant={size === 'xs' ? 'ghost' : 'default'}
        className={cn('shrink-0', size === 'xs' ? 'h-8 px-2.5 text-xs' : 'h-10')}
        onClick={() => void copy()}
      >
        {state === 'copied' ? 'Copied' : children}
      </Button>
    </div>
  );
}

function PartText({ part }: { part: Part }) {
  return (
    <p className="whitespace-pre-wrap break-words font-sans text-[15px] leading-relaxed text-foreground">
      {part.text}
    </p>
  );
}

function PartCounter({ part }: { part: Part }) {
  const over = part.charCount - part.charLimit;

  return (
    <div className="space-y-0.5 font-sans text-xs tabular-nums">
      <p className={cn(over > 0 ? 'text-red-700 dark:text-red-300' : 'text-muted-foreground')}>
        {formatCount(part.charCount)} / {formatCount(part.charLimit)} characters
      </p>
      {over > 0 && (
        <p className="font-medium text-red-700 dark:text-red-300">
          {`${formatCount(over)} characters over X's ${formatCount(part.charLimit)}-character limit`}
        </p>
      )}
    </div>
  );
}

/** The Final comes first because it is what goes to X; the Draft below shows what the rewrite changed. */
export function VersionView({ version }: { version: Version }) {
  const finalId = useId();
  const draftId = useId();

  return (
    <div className="space-y-3">
      <article
        aria-labelledby={finalId}
        className="space-y-4 rounded-lg border border-border bg-card p-4 shadow-sm sm:p-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id={finalId} className="font-sans text-sm font-semibold text-foreground">
            Final
          </h3>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <FinalToXActions version={version} />
            <CopyButton
              text={version.parts.map((part) => part.text).join('\n\n')}
              event="post_final_copied"
            >
              Copy Final
            </CopyButton>
          </div>
        </div>
        {version.format === 'thread' ? (
          <ThreadParts
            parts={version.parts}
            aside={(part, number) => (
              <CopyButton text={part.text} event="post_part_copied" size="xs">
                Copy<span className="sr-only"> Part {number}</span>
              </CopyButton>
            )}
          >
            {(part) => (
              <>
                <PartText part={part} />
                <PartCounter part={part} />
              </>
            )}
          </ThreadParts>
        ) : (
          version.parts.map((part, index) => (
            <div key={index} className="space-y-4">
              <PartText part={part} />
              <PartCounter part={part} />
            </div>
          ))
        )}
        <SlopTells tells={version.tells} />
      </article>

      <article aria-labelledby={draftId} className="space-y-2 rounded-lg bg-muted/50 p-4 sm:p-5">
        <div>
          <h3 id={draftId} className="font-sans text-sm font-semibold text-foreground">
            Draft
          </h3>
          <p className="font-sans text-xs text-muted-foreground">
            Written first, before the rewrite that made it the Final.
          </p>
        </div>
        {version.draftParts.map((text, index) => (
          <p
            key={index}
            className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-muted-foreground"
          >
            {text}
          </p>
        ))}
      </article>
    </div>
  );
}
