import { useId, useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { POSITIONING_MAX_CHARS } from '@/services/positioningService';
import { usePositioning } from './usePositioning';

/** How close to the limit the count starts showing. */
const COUNT_SHOWN_WITHIN = 400;

/**
 * The Positioning: one textarea the User writes, or has drafted, and saves. The Persona page
 * shows it as a section with Save. Onboarding's Persona step shows it as the page: it drafts on
 * open, and Continue saves, then calls `onContinue`, which resolves with why it couldn't go on.
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
    draft,
    drafting,
    canDraft,
    canRequestDraft,
    justDrafted,
  } = usePositioning({ draftOnOpen: step });
  const [continuing, setContinuing] = useState(false);
  const id = useId();
  const headingId = `${id}-heading`;
  const helperId = `${id}-helper`;
  const errorId = `${id}-error`;
  const limitId = `${id}-limit`;
  const busy = loading === 'loading' || drafting;
  const nearLimit = length >= POSITIONING_MAX_CHARS - COUNT_SHOWN_WITHIN;
  // maxLength counts UTF-16 units, so it grows by one for each character that takes two.
  const maxUnits = POSITIONING_MAX_CHARS + text.length - length;
  const Heading = step ? 'h1' : 'h2';
  // Continue goes on with unchanged text too: the step needs a Positioning, not a change.
  const canSubmit = step ? idle && hasText && !continuing : canSave;

  const goOn = async () => {
    setContinuing(true);
    const problem = (await save()) ? await onContinue?.() : undefined;
    // On success the gate moves the User on, so the step stays locked until it unmounts.
    if (problem !== null) setContinuing(false);
    if (problem) fail(problem);
  };

  return (
    <section aria-labelledby={headingId} className="space-y-5">
      <div className="space-y-1">
        <Heading
          id={headingId}
          className={cn(
            'font-sans font-semibold tracking-[-0.015em] text-foreground',
            step ? 'text-2xl/[30px]' : 'text-xl',
          )}
        >
          Who you are on X
        </Heading>
        <p className="font-sans text-sm text-muted-foreground">
          Pumpkit plans every post around this.
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
            if (step) void goOn();
            else void save();
          }}
        >
          <div className="space-y-2">
            <Textarea
              aria-labelledby={headingId}
              aria-describedby={error ? `${errorId} ${helperId}` : helperId}
              aria-invalid={textRefused ? true : undefined}
              value={busy ? '' : text}
              onChange={(event) => edit(event.target.value)}
              placeholder={
                loading === 'loading'
                  ? 'Loading your positioning…'
                  : drafting
                    ? 'Reading your X profile…'
                    : 'I’m … I post about … I write for … I post to …'
              }
              disabled={busy || continuing}
              maxLength={maxUnits}
              rows={7}
              className="min-h-40 resize-y font-sans text-base/6 text-foreground focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring sm:text-sm/6"
            />
            {error && (
              <p id={errorId} role="alert" className="font-sans text-sm text-destructive">
                {error}
              </p>
            )}
            <p id={helperId} className="font-sans text-sm text-muted-foreground">
              Cover: who you are · what you post about · who you write for · what you post for ·
              what you can point to
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
            <div className="mr-auto flex flex-wrap items-center gap-x-3 gap-y-1">
              <Button
                type="button"
                variant="outline"
                className="h-11 sm:h-10"
                disabled={!canRequestDraft || continuing}
                aria-describedby={canDraft ? undefined : limitId}
                onClick={() => void draft()}
              >
                Draft again from my X profile
              </Button>
              {!canDraft && (
                <p id={limitId} className="font-sans text-sm text-muted-foreground">
                  You can draft again tomorrow.
                </p>
              )}
            </div>
            {nearLimit && (
              <p className="font-mono text-xs tabular-nums text-muted-foreground">
                {length.toLocaleString('en-US')} / {POSITIONING_MAX_CHARS.toLocaleString('en-US')}
              </p>
            )}
            <p role="status" className="font-sans text-sm text-muted-foreground">
              {justSaved && !step
                ? 'Saved'
                : justDrafted
                  ? step
                    ? 'Drafted from your X profile.'
                    : 'Drafted from your X profile. Save to keep it.'
                  : ''}
            </p>
            <Button type="submit" className="h-11 sm:h-10" disabled={!canSubmit}>
              {step ? (continuing ? 'Continuing…' : 'Continue') : saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
