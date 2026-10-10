import { useEffect, useId, useState } from 'react';
import { Button } from '@/components/ui/button';
import { FinalToXActions } from '@/features/scheduledPosts/FinalToX';
import { track } from '@/lib/analytics';
import { formatCount } from '@/lib/characters';
import { cn } from '@/lib/utils';
import { SlopTells } from './SlopTells';
import type { Version } from '@/services/postService';

function CopyFinalButton({ final }: { final: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (state !== 'copied') return;
    const timer = window.setTimeout(() => setState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(final);
      setState('copied');
      track('post_final_copied');
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
      <Button size="sm" className="h-10 shrink-0" onClick={() => void copy()}>
        {state === 'copied' ? 'Copied' : 'Copy Final'}
      </Button>
    </div>
  );
}

/** The Final comes first because it is what goes to X; the Draft below shows what the rewrite changed. */
export function VersionView({ version }: { version: Version }) {
  const finalId = useId();
  const draftId = useId();
  const over = version.finalCharCount - version.finalCharLimit;

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
            <CopyFinalButton final={version.final} />
          </div>
        </div>
        <p className="whitespace-pre-wrap break-words font-sans text-[15px] leading-relaxed text-foreground">
          {version.final}
        </p>
        <div className="space-y-0.5 font-sans text-xs tabular-nums">
          <p className={cn(over > 0 ? 'text-red-700 dark:text-red-300' : 'text-muted-foreground')}>
            {formatCount(version.finalCharCount)} / {formatCount(version.finalCharLimit)} characters
          </p>
          {over > 0 && (
            <p className="font-medium text-red-700 dark:text-red-300">
              {`${formatCount(over)} characters over X's ${formatCount(version.finalCharLimit)}-character limit`}
            </p>
          )}
        </div>
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
        <p className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-muted-foreground">
          {version.draft}
        </p>
      </article>
    </div>
  );
}
