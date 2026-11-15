import { useId, useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { XLogo } from '@/components/XLogo';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { POSITIONING_MAX_CHARS } from '@/services/positioningService';
import { usePositioning } from './usePositioning';

/** How close to the limit the count starts showing. */
const COUNT_SHOWN_WITHIN = 400;

/**
 * With `onContinue`, Continue saves and then calls it; it resolves with why the User couldn't go
 * on, or null once they do.
 */
export function PositioningPanel({ onContinue }: { onContinue?: () => Promise<string | null> }) {
  const step = onContinue !== undefined;
  const {
    loading,
    reload,
    text,
    length,
    edit,
    save,
    saving,
    idle,
    hasText,
    canSave,
    fail,
    error,
    textRefused,
    justSaved,
    drafting,
    draftReason,
    drafted,
  } = usePositioning({ draftOnOpen: step });
  const [continuing, setContinuing] = useState(false);
  const id = useId();
  const headingId = `${id}-heading`;
  const adviceId = `${id}-advice`;
  const errorId = `${id}-error`;
  const readingId = `${id}-reading`;
  const reasonId = `${id}-reason`;
  const busy = loading === 'loading' || drafting;
  const nearLimit = length >= POSITIONING_MAX_CHARS - COUNT_SHOWN_WITHIN;
  // maxLength counts UTF-16 units, so it grows by one for each character that takes two.
  const maxUnits = POSITIONING_MAX_CHARS + text.length - length;
  const Heading = step ? 'h1' : 'h2';
  // Continue goes on with unchanged text too: the step needs a Positioning, not a change.
  const canSubmit = step ? idle && hasText && !continuing : canSave;
  const describedBy = [drafting && readingId, draftReason && reasonId, error && errorId, adviceId]
    .filter(Boolean)
    .join(' ');
  // Announces the draft as it starts and lands; a failed one's reason shows here too.
  const draftStatus = drafting
    ? 'Reading your X profile…'
    : drafted
      ? 'Your draft is ready to edit.'
      : '';
  const count = nearLimit && (
    <p className="font-mono text-xs tabular-nums text-muted-foreground">
      {length.toLocaleString('en-US')} / {POSITIONING_MAX_CHARS.toLocaleString('en-US')}
    </p>
  );

  const saveAndContinue = async (continueOn: () => Promise<string | null>) => {
    setContinuing(true);
    if (!(await save())) {
      setContinuing(false);
      return;
    }
    const notContinued = await continueOn();
    // Once the User goes on, the gate unmounts the step, so it stays locked until then.
    if (notContinued === null) return;
    setContinuing(false);
    fail(notContinued);
  };

  return (
    <section aria-labelledby={headingId} className="space-y-5">
      <div className="space-y-1">
        <Heading
          id={headingId}
          className={cn(
            'font-sans font-semibold tracking-[-0.015em] text-foreground',
            step ? 'text-2xl leading-tight' : 'text-xl',
          )}
        >
          Who you are on <XLogo />
        </Heading>
        <p id={adviceId} className="font-sans text-sm text-muted-foreground">
          Pumpkit plans every post around this. Two or three sentences are enough.
        </p>
      </div>

      {loading === 'failed' ? (
        <ErrorBanner message="Couldn't load your positioning." onRetry={reload} />
      ) : (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            if (onContinue) void saveAndContinue(onContinue);
            else void save();
          }}
        >
          <div className="space-y-2">
            <div className="relative">
              <Textarea
                aria-labelledby={headingId}
                aria-describedby={describedBy}
                aria-invalid={textRefused ? true : undefined}
                value={busy ? '' : text}
                onChange={(event) => edit(event.target.value)}
                placeholder={
                  loading === 'loading'
                    ? 'Loading your positioning…'
                    : drafting
                      ? undefined
                      : 'I’m … I post about … I write for … I post to …'
                }
                disabled={busy || continuing}
                maxLength={maxUnits}
                rows={7}
                className="min-h-40 resize-y font-sans text-base/6 text-foreground focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring sm:text-sm/6"
              />
              {drafting && (
                <p
                  id={readingId}
                  className="pointer-events-none absolute inset-0 flex items-center justify-center gap-[0.3em] px-4 text-center font-sans text-sm text-muted-foreground motion-safe:animate-pulse"
                >
                  Reading your <XLogo decorative />
                  <span className="sr-only">X</span> profile…
                </p>
              )}
            </div>
            <p
              id={reasonId}
              role="status"
              className={
                draftReason && !drafting ? 'font-sans text-sm text-muted-foreground' : 'sr-only'
              }
            >
              {draftReason && !drafting ? draftReason : draftStatus}
            </p>
            {error && (
              <p id={errorId} role="alert" className="font-sans text-sm text-destructive">
                {error}
              </p>
            )}
          </div>

          {step ? (
            <div className="space-y-3">
              {count && <div className="flex justify-end">{count}</div>}
              <Button type="submit" className="h-11 w-full" disabled={!canSubmit}>
                {continuing ? 'Continuing…' : 'Continue'}
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
              <div className="mr-auto">{count}</div>
              <p role="status" className="font-sans text-sm text-muted-foreground">
                {justSaved ? 'Saved' : ''}
              </p>
              <Button type="submit" className="h-11 sm:h-10" disabled={!canSubmit}>
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
          )}
        </form>
      )}
    </section>
  );
}
