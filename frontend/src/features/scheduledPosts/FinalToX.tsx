import { useId, useMemo, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useBilling } from '@/features/billing/useBilling';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { track } from '@/lib/analytics';
import { xWeightedLength } from '@/lib/xLength';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import type { Version } from '@/services/postService';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';
import { earliestInputValue, TIME_ZONE } from './localTime';
import { XLengthCounter } from './XLengthCounter';

type Action = 'schedule' | 'postNow';

const BILLING_SOURCE: Record<Action, string> = {
  schedule: 'final_schedule',
  postNow: 'final_post_now',
};

const dateTime = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' });

const LINK = 'font-medium text-foreground underline underline-offset-2';

/** What came of sending the Final, in place of the form. */
function Outcome({ created }: { created: ScheduledPost }) {
  if (created.state === 'failed') {
    return (
      <p className="font-sans text-sm text-red-700 dark:text-red-300">{created.failedReason}</p>
    );
  }
  if (created.state === 'published') {
    return (
      <p className="flex flex-wrap gap-x-3 font-sans text-sm text-foreground">
        <span>Published on X.</span>
        {created.xPostUrl && (
          <a href={created.xPostUrl} target="_blank" rel="noreferrer" className={LINK}>
            View on X
          </a>
        )}
      </p>
    );
  }
  return (
    <p className="flex flex-wrap gap-x-3 font-sans text-sm text-foreground">
      <span>Scheduled for {dateTime.format(new Date(created.publishAt))}.</span>
      <Link to="/scheduled" className={LINK}>
        See Scheduled posts
      </Link>
    </p>
  );
}

/**
 * Schedules the Final for a time the User picks, or posts it now after a confirmation. The
 * Scheduled post keeps its own copy of the text, so later Feedback leaves it alone.
 */
function FinalToXDialog({
  action,
  version,
  onClose,
}: {
  action: Action;
  version: Version;
  onClose: () => void;
}) {
  const { refresh: refreshSubscribed } = useSubscribed();
  const billing = useBilling();
  const {
    connection,
    busy: connecting,
    error: connectError,
    connect,
    reload: reloadXConnection,
  } = useXConnectionContext();
  const whenId = useId();
  /** The picked time as the input holds it, in the browser's timezone; '' when none. */
  const [when, setWhen] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ScheduledPost | null>(null);
  const length = useMemo(() => xWeightedLength(version.final), [version.final]);
  const postNow = action === 'postNow';

  const send = async (e: FormEvent) => {
    e.preventDefault();
    setSending(true);
    setError(null);
    try {
      const result = postNow
        ? await scheduledPostService.postNow(version.final, version.id)
        : // A datetime-local value without an offset parses as local time.
          await scheduledPostService.schedule(
            version.final,
            new Date(when).toISOString(),
            version.id,
          );
      track('scheduled_post_created', { source: 'final', post_now: postNow });
      setCreated(result);
      // A Failed one may have flagged the X connection for reconnecting.
      if (result.state === 'failed') void reloadXConnection();
    } catch (e) {
      if (errorStatus(e) === 403) {
        refreshSubscribed();
        onClose();
        billing.open(BILLING_SOURCE[action]);
        return;
      }
      setError(
        errorMessage(
          e,
          postNow
            ? "Couldn't post to X. Please try again."
            : "Couldn't schedule the post. Please try again.",
        ),
      );
      // A 409 means the X connection changed elsewhere: show its current state.
      if (errorStatus(e) === 409) void reloadXConnection();
    } finally {
      setSending(false);
    }
  };

  const title = postNow ? 'Post this Final now?' : 'Schedule this Final';
  const ready = connection && !connection.needsReconnect;

  let description;
  let body;
  let footer;
  if (created) {
    description = postNow ? 'Sent to X.' : 'Pumpkit publishes it at that time.';
    body = <Outcome created={created} />;
    footer = (
      <Button type="button" className="h-10" onClick={onClose}>
        Close
      </Button>
    );
  } else if (connection === undefined) {
    description = 'Checking your X connection…';
  } else if (!ready) {
    description = connection
      ? 'Reconnect X to post this Final.'
      : 'Connect your X account to post this Final.';
    body = connectError && <ErrorBanner message={connectError} />;
    footer = (
      <>
        <Button type="button" variant="outline" className="h-10" onClick={onClose}>
          Cancel
        </Button>
        <Button type="button" className="h-10" disabled={connecting} onClick={() => void connect()}>
          {connection ? 'Reconnect X' : 'Connect X'}
        </Button>
      </>
    );
  } else {
    description = postNow
      ? `It goes out on @${connection.handle} straight away.`
      : `It goes out on @${connection.handle} at the time you pick.`;
    body = (
      <>
        <div className="space-y-1.5 rounded-lg bg-muted/50 p-3">
          <p className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words font-sans text-sm text-foreground">
            {version.final}
          </p>
          <XLengthCounter length={length} limit={connection.charLimit} />
        </div>
        {!postNow && (
          <div className="space-y-1.5">
            <label htmlFor={whenId} className="block font-sans text-sm font-medium text-foreground">
              Date and time
            </label>
            <Input
              id={whenId}
              type="datetime-local"
              value={when}
              min={earliestInputValue()}
              onChange={(e) => setWhen(e.target.value)}
              disabled={sending}
              className="sm:w-64"
            />
            <p className="font-sans text-xs text-muted-foreground">
              Times are in your timezone, {TIME_ZONE}.
            </p>
          </div>
        )}
        {error && <ErrorBanner message={error} />}
      </>
    );
    const unsendable = sending || length > connection.charLimit || (!postNow && !when);
    footer = (
      <>
        <Button type="button" variant="outline" className="h-10" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" className="h-10" disabled={unsendable}>
          {postNow ? 'Post now' : 'Schedule'}
        </Button>
      </>
    );
  }

  return (
    <Dialog open onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-[520px] max-sm:h-auto">
        <form onSubmit={send} className="space-y-4">
          <DialogHeader>
            <DialogTitle className="font-sans text-base font-semibold tracking-tight">
              {title}
            </DialogTitle>
            <DialogDescription className="font-sans">{description}</DialogDescription>
          </DialogHeader>
          {body}
          {footer && <DialogFooter className="justify-end gap-2">{footer}</DialogFooter>}
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Schedule and Post now on a Version's Final; a User who isn't Subscribed gets Billing. */
export function FinalToXActions({ version }: { version: Version }) {
  const { subscribed } = useSubscribed();
  const billing = useBilling();
  const [action, setAction] = useState<Action | null>(null);

  const start = (next: Action) => {
    if (subscribed === false) billing.open(BILLING_SOURCE[next]);
    else setAction(next);
  };

  return (
    <>
      <Button variant="outline" size="sm" className="h-10" onClick={() => start('postNow')}>
        Post now
      </Button>
      <Button variant="outline" size="sm" className="h-10" onClick={() => start('schedule')}>
        Schedule
      </Button>
      {action && (
        <FinalToXDialog action={action} version={version} onClose={() => setAction(null)} />
      )}
    </>
  );
}
