import { useMemo, useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { xWeightedLength } from '@/lib/xLength';
import { localInputValue, TIME_ZONE } from './localTime';
import { XLengthCounter } from './XLengthCounter';

/**
 * Where the User types a text and either schedules it for a date and time in the browser's
 * timezone or posts it on their X account straight away.
 */
export function Composer({
  posting,
  error,
  onPostNow,
  onSchedule,
}: {
  posting: boolean;
  error: string | null;
  onPostNow: (text: string) => Promise<boolean>;
  onSchedule: (text: string, publishAt: string) => Promise<boolean>;
}) {
  const { subscribed } = useSubscribed();
  const { connection, busy: connecting, connect } = useXConnectionContext();
  const [text, setText] = useState('');
  /** The picked time as the input holds it, in the browser's timezone; '' when none. */
  const [when, setWhen] = useState('');
  const length = useMemo(() => xWeightedLength(text), [text]);

  const clear = () => {
    setText('');
    setWhen('');
  };

  const schedule = async (e: FormEvent) => {
    e.preventDefault();
    // A datetime-local value without an offset parses as local time.
    if (await onSchedule(text, new Date(when).toISOString())) clear();
  };

  const postNow = async () => {
    if (await onPostNow(text)) clear();
  };

  let action;
  if (subscribed === false) {
    action = (
      <SubscribePrompt message="Posting to X needs a Subscription." source="scheduled_post_now" />
    );
  } else if (connection === undefined || subscribed === null) {
    action = null;
  } else if (connection === null || connection.needsReconnect) {
    action = (
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="font-sans text-sm text-foreground">
          {connection ? 'Reconnect X to post.' : 'Connect your X account to post.'}
        </p>
        <Button
          type="button"
          size="sm"
          className="h-10 shrink-0"
          disabled={connecting}
          onClick={() => void connect()}
        >
          {connection ? 'Reconnect X' : 'Connect X'}
        </Button>
      </div>
    );
  } else {
    const unsendable = posting || length > connection.charLimit || !text.trim();
    action = (
      <div className="space-y-3">
        <div className="space-y-1.5">
          <label
            htmlFor="composer-when"
            className="block font-sans text-sm font-medium text-foreground"
          >
            Date and time
          </label>
          <Input
            id="composer-when"
            type="datetime-local"
            value={when}
            min={localInputValue(new Date(Date.now() + 60_000))}
            onChange={(e) => setWhen(e.target.value)}
            disabled={posting}
            className="sm:w-64"
          />
          <p className="font-sans text-xs text-muted-foreground">
            Times are in your timezone, {TIME_ZONE}.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <XLengthCounter length={length} limit={connection.charLimit} />
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-10"
              disabled={unsendable}
              onClick={() => void postNow()}
            >
              Post now
            </Button>
            <Button type="submit" className="h-10" disabled={unsendable || !when}>
              Schedule
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <section aria-labelledby="composer-heading" className="space-y-3">
      <h2 id="composer-heading" className="font-sans text-base font-semibold text-foreground">
        Post to X
      </h2>
      <form onSubmit={schedule} className="space-y-3">
        <label htmlFor="composer-text" className="sr-only">
          Post text
        </label>
        <Textarea
          id="composer-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Write what goes out on X"
          rows={5}
          disabled={posting}
        />
        {error && <ErrorBanner message={error} />}
        {action}
      </form>
    </section>
  );
}
