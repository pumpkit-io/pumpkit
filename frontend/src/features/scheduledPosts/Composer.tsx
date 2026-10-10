import { useMemo, useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { xWeightedLength } from '@/lib/xLength';
import { XLengthCounter } from './XLengthCounter';

/** Where the User types a text and posts it on their X account straight away. */
export function Composer({
  posting,
  error,
  onPostNow,
}: {
  posting: boolean;
  error: string | null;
  onPostNow: (text: string) => Promise<boolean>;
}) {
  const { subscribed } = useSubscribed();
  const { connection, busy: connecting, connect } = useXConnectionContext();
  const [text, setText] = useState('');
  const length = useMemo(() => xWeightedLength(text), [text]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (await onPostNow(text)) setText('');
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
    const over = length > connection.charLimit;
    action = (
      <div className="flex items-center justify-between gap-3">
        <XLengthCounter length={length} limit={connection.charLimit} />
        <Button type="submit" className="h-10" disabled={posting || over || !text.trim()}>
          {posting ? 'Posting…' : 'Post now'}
        </Button>
      </div>
    );
  }

  return (
    <section aria-labelledby="composer-heading" className="space-y-3">
      <h2 id="composer-heading" className="font-sans text-base font-semibold text-foreground">
        Post to X
      </h2>
      <form onSubmit={submit} className="space-y-3">
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
