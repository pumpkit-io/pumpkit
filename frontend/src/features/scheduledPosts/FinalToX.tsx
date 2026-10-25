import { useMemo, useState, type FormEvent } from 'react';
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
import { useBilling } from '@/features/billing/useBilling';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { ConnectXPrompt } from '@/features/xConnection/ConnectXPrompt';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { xWeightedLength } from '@/lib/xLength';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { destinationFrom, PROFILE_DRAFT, type DestinationDraft } from './communities';
import { DestinationField } from './DestinationField';
import { PublishTimeField } from './PublishTimeField';
import { useCreateScheduledPost, X_BUSY_NOTICE } from './useCreateScheduledPost';
import { XLengthCounter } from './XLengthCounter';

type Action = 'schedule' | 'postNow';

const BILLING_SOURCE: Record<Action, string> = {
  schedule: 'final_schedule',
  postNow: 'final_post_now',
};

const dateTime = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' });

const LINK = 'font-medium text-foreground underline underline-offset-2';

/** The dialog's description once the Final is sent, by where the Scheduled post ended up. */
function outcomeDescription(created: ScheduledPost, postNow: boolean): string {
  if (created.state === 'published') return 'Published on X.';
  if (created.state === 'failed') return 'This Scheduled post Failed.';
  return postNow ? X_BUSY_NOTICE : 'Pumpkit publishes it at that time.';
}

/** What came of sending the Final, in place of the form. */
function Outcome({ created, postNow }: { created: ScheduledPost; postNow: boolean }) {
  if (created.state === 'failed') {
    return (
      <p className="font-sans text-sm text-red-700 dark:text-red-300">{created.failedReason}</p>
    );
  }
  if (created.state === 'published') {
    return (
      created.xPostUrl && (
        <a href={created.xPostUrl} target="_blank" rel="noreferrer" className={LINK}>
          View on X
        </a>
      )
    );
  }
  return (
    <p className="flex flex-wrap gap-x-3 font-sans text-sm text-foreground">
      {!postNow && <span>Scheduled for {dateTime.format(new Date(created.publishAt))}.</span>}
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
  const billing = useBilling();
  const { connection } = useXConnectionContext();
  const { sending, error, create } = useCreateScheduledPost();
  /** The picked time as the input holds it, in the browser's timezone; '' when none. */
  const [when, setWhen] = useState('');
  const [created, setCreated] = useState<ScheduledPost | null>(null);
  const [draft, setDraft] = useState<DestinationDraft>(PROFILE_DRAFT);
  const destination = destinationFrom(draft);
  // The Scheduled post copies every Part of the Final; X counts each Part on its own.
  const lengths = useMemo(
    () => version.parts.map((part) => xWeightedLength(part.text)),
    [version.parts],
  );
  const postNow = action === 'postNow';

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!destination) return;
    const outcome = await create(
      postNow
        ? { sourceVersionId: version.id, destination, postNow: true }
        : {
            sourceVersionId: version.id,
            destination,
            postNow: false,
            // A datetime-local value without an offset parses as local time.
            publishAt: new Date(when).toISOString(),
          },
    );
    if (outcome.kind === 'created') setCreated(outcome.scheduledPost);
    if (outcome.kind === 'notSubscribed') {
      onClose();
      billing.open(BILLING_SOURCE[action]);
    }
  };

  const title = postNow ? 'Post this Final now?' : 'Schedule this Final';
  const ready = connection && !connection.needsReconnect;

  let description;
  let body;
  let footer;
  if (created) {
    description = outcomeDescription(created, postNow);
    body = <Outcome created={created} postNow={postNow} />;
    footer = (
      <Button type="button" className="h-10" onClick={onClose}>
        Close
      </Button>
    );
  } else if (connection === undefined) {
    description = 'Checking your X connection…';
  } else if (!ready) {
    description = 'Pumpkit publishes on the X account you connect.';
    body = <ConnectXPrompt what="this Final" showError />;
    footer = (
      <Button type="button" variant="outline" className="h-10" onClick={onClose}>
        Cancel
      </Button>
    );
  } else {
    const where =
      draft.kind !== 'profile'
        ? `from @${connection.handle} into the Community`
        : `on @${connection.handle}`;
    description = `It goes out ${where} ${postNow ? 'straight away' : 'at the time you pick'}.`;
    body = (
      <>
        <div className="max-h-48 space-y-3 overflow-y-auto rounded-lg bg-muted/50 p-3">
          {version.parts.map((part, i) => (
            <div key={i} className="space-y-1.5">
              <p className="whitespace-pre-wrap break-words font-sans text-sm text-foreground">
                {part.text}
              </p>
              <XLengthCounter length={lengths[i]} limit={connection.charLimit} />
            </div>
          ))}
        </div>
        <DestinationField value={draft} onChange={setDraft} disabled={sending} />
        {!postNow && <PublishTimeField value={when} onChange={setWhen} disabled={sending} />}
        {error && <ErrorBanner message={error} />}
      </>
    );
    const unsendable =
      sending ||
      lengths.some((length) => length > connection.charLimit) ||
      (!postNow && !when) ||
      destination === null;
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
