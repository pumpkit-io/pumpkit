import { useId } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { POSITIONING_MAX_CHARS } from '@/services/positioningService';
import { usePositioning } from './usePositioning';

/** How close to the limit the count starts showing. */
const COUNT_SHOWN_WITHIN = 400;

/** The Persona page's Positioning: one textarea the User writes, or has drafted, and saves. */
export function PositioningPanel() {
  const {
    loading,
    reload,
    text,
    length,
    edit,
    save,
    saving,
    canSave,
    error,
    textRefused,
    justSaved,
    draft,
    drafting,
    canDraft,
    canRequestDraft,
    justDrafted,
  } = usePositioning();
  const id = useId();
  const headingId = `${id}-heading`;
  const helperId = `${id}-helper`;
  const errorId = `${id}-error`;
  const limitId = `${id}-limit`;
  const busy = loading === 'loading' || drafting;
  const nearLimit = length >= POSITIONING_MAX_CHARS - COUNT_SHOWN_WITHIN;
  // maxLength counts UTF-16 units, so it grows by one for each character that takes two.
  const maxUnits = POSITIONING_MAX_CHARS + text.length - length;

  return (
    <section aria-labelledby={headingId} className="space-y-5">
      <div className="space-y-1">
        <h2
          id={headingId}
          className="font-sans text-xl font-semibold tracking-[-0.015em] text-foreground"
        >
          Who you are on X
        </h2>
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
            if (canSave) void save();
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
              disabled={busy}
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
                disabled={!canRequestDraft}
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
              {justSaved
                ? 'Saved'
                : justDrafted
                  ? 'Drafted from your X profile. Save to keep it.'
                  : ''}
            </p>
            <Button type="submit" className="h-11 sm:h-10" disabled={!canSave}>
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
