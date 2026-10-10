import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnection } from './useXConnection';

/** The X account Scheduled posts go out on, with connect and disconnect. */
export function XConnectionPanel({ notice }: { notice: string | null }) {
  const { subscribed } = useSubscribed();
  const { connection, loadFailed, busy, error, connect, disconnect } = useXConnection();

  return (
    <section aria-labelledby="x-connection-heading" className="space-y-4">
      <div className="space-y-1">
        <h2 id="x-connection-heading" className="font-sans text-base font-semibold text-foreground">
          X connection
        </h2>
        <p className="font-sans text-sm text-muted-foreground">
          The X account Pumpkit publishes your Scheduled posts on. Pumpkit never sees your X
          password.
        </p>
      </div>

      {notice && <LimitNotice message={notice} />}
      {error && <ErrorBanner message={error} />}

      {loadFailed ? (
        <ErrorBanner message="Couldn't load your X connection. Reload the page to try again." />
      ) : connection === undefined ? (
        <p role="status" className="font-sans text-sm text-muted-foreground">
          Loading your X connection…
        </p>
      ) : connection ? (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-border px-4 py-2">
          <span className="font-sans text-sm font-medium text-foreground">
            @{connection.handle}
          </span>
          <Button
            variant="outline"
            size="sm"
            className="h-10 shrink-0"
            disabled={busy}
            onClick={() => void disconnect()}
          >
            Disconnect
          </Button>
        </div>
      ) : subscribed === false ? (
        <SubscribePrompt
          message="Connecting X needs a Subscription."
          source="scheduled_x_connection"
        />
      ) : subscribed === true ? (
        <Button className="h-10" disabled={busy} onClick={() => void connect()}>
          {busy ? 'Opening X…' : 'Connect X'}
        </Button>
      ) : null}
    </section>
  );
}
