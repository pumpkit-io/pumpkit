import { useMemo, useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { ConnectXPrompt } from '@/features/xConnection/ConnectXPrompt';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { xWeightedLength } from '@/lib/xLength';
import { PublishTimeField } from './PublishTimeField';
import { XLengthCounter } from './XLengthCounter';

/**
 * Where the User types a text and either schedules it for a date and time in the browser's
 * timezone or posts it on their X account straight away.
 */
export function Composer({
  posting,
  error,
  notice,
  onPostNow,
  onSchedule,
}: {
  posting: boolean;
  error: string | null;
  /** What came of the last send, when it needs saying. */
  notice: string | null;
  onPostNow: (text: string) => Promise<boolean>;
  onSchedule: (text: string, publishAt: string) => Promise<boolean>;
}) {
  const { subscribed } = useSubscribed();
  const { connection } = useXConnectionContext();
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
    action = <ConnectXPrompt />;
  } else {
    const unsendable = posting || length > connection.charLimit || !text.trim();
    action = (
      <div className="space-y-3">
        <PublishTimeField value={when} onChange={setWhen} disabled={posting} />
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
        {notice && (
          <p role="status" className="font-sans text-sm text-foreground">
            {notice}
          </p>
        )}
        {action}
      </form>
    </section>
  );
}
