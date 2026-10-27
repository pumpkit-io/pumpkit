import { useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { ConnectXPrompt } from '@/features/xConnection/ConnectXPrompt';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import type { Destination } from '@/services/scheduledPostService';
import { destinationFrom, PROFILE_DRAFT } from './communities';
import { DestinationField } from './DestinationField';
import { PartEditor } from './PartEditor';
import { partDrafts, partsSendable, partTexts } from './partDrafts';
import { PublishTimeField } from './PublishTimeField';

/**
 * Where the User types a text, or a Thread Part by Part, picks their profile or a Community, and
 * either schedules it for a date and time in the browser's timezone or posts it on their X
 * account straight away.
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
  onPostNow: (parts: string[], destination: Destination) => Promise<boolean>;
  onSchedule: (parts: string[], publishAt: string, destination: Destination) => Promise<boolean>;
}) {
  const { subscribed } = useSubscribed();
  const { connection } = useXConnectionContext();
  const [parts, setParts] = useState(() => partDrafts(['']));
  /** The picked time as the input holds it, in the browser's timezone; '' when none. */
  const [when, setWhen] = useState('');
  // Kept after a send, so a run of posts can go to the same Community.
  const [draft, setDraft] = useState(PROFILE_DRAFT);
  const destination = destinationFrom(draft);

  const clear = () => {
    setParts(partDrafts(['']));
    setWhen('');
  };

  const schedule = async (e: FormEvent) => {
    e.preventDefault();
    // A datetime-local value without an offset parses as local time.
    if (!destination) return;
    if (await onSchedule(partTexts(parts), new Date(when).toISOString(), destination)) clear();
  };

  const postNow = async () => {
    if (!destination) return;
    if (await onPostNow(partTexts(parts), destination)) clear();
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
    const unsendable =
      posting || !partsSendable(parts, connection.charLimit) || destination === null;
    action = (
      <div className="space-y-3">
        <DestinationField value={draft} onChange={setDraft} disabled={posting} />
        <PublishTimeField value={when} onChange={setWhen} disabled={posting} />
        <div className="flex flex-wrap items-center justify-end gap-3">
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
        <PartEditor
          parts={parts}
          onChange={setParts}
          charLimit={connection && !connection.needsReconnect ? connection.charLimit : null}
          placeholder="Write what goes out on X"
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
