import { useId } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { POSITIONING_MAX_CHARS } from '@/services/positioningService';
import { usePositioning } from './usePositioning';

/** How close to the limit the count starts showing. */
const COUNT_SHOWN_WITHIN = 400;

/** The Persona page's Positioning: one textarea the User writes and saves. */
export function PositioningPanel() {
  const { loading, reload, text, edit, save, saving, canSave, error, textRefused, justSaved } =
    usePositioning();
  const id = useId();
  const headingId = `${id}-heading`;
  const helperId = `${id}-helper`;
  const errorId = `${id}-error`;
  const nearLimit = text.length >= POSITIONING_MAX_CHARS - COUNT_SHOWN_WITHIN;

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
              value={loading === 'loading' ? '' : text}
              onChange={(event) => edit(event.target.value)}
              placeholder={
                loading === 'loading'
                  ? 'Loading your positioning…'
                  : 'I’m … I post about … I write for … I post to …'
              }
              disabled={loading === 'loading'}
              maxLength={POSITIONING_MAX_CHARS}
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
            {nearLimit && (
              <p className="mr-auto font-mono text-xs tabular-nums text-muted-foreground">
                {text.length.toLocaleString('en-US')} /{' '}
                {POSITIONING_MAX_CHARS.toLocaleString('en-US')}
              </p>
            )}
            <p role="status" className="font-sans text-sm text-muted-foreground">
              {justSaved ? 'Saved' : ''}
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
