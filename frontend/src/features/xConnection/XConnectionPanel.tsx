import { useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { DisconnectXDialog } from './DisconnectXDialog';
import { useXConnectionContext } from './useXConnectionContext';

/** The X account Scheduled posts go out on, with connect and disconnect. */
export function XConnectionPanel({ notice }: { notice: string | null }) {
  const { subscribed } = useSubscribed();
  const { connection, loadFailed, busy, error, connect, disconnect, reload } =
    useXConnectionContext();
  const [confirming, setConfirming] = useState(false);
  /** False while the waiting count is refreshed: it may have changed since the page loaded. */
  const [counted, setCounted] = useState(false);

  const askToDisconnect = async () => {
    setConfirming(true);
    setCounted(false);
    await reload();
    setCounted(true);
  };

  const confirmDisconnect = () => {
    setConfirming(false);
    void disconnect();
  };

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
        <div className="space-y-3 rounded-lg border border-border px-4 py-2">
          <div className="flex items-center justify-between gap-3">
            <span className="font-sans text-sm font-medium text-foreground">
              @{connection.handle}
            </span>
            <Button
              variant="outline"
              size="sm"
              className="h-10 shrink-0"
              disabled={busy}
              onClick={() => void askToDisconnect()}
            >
              Disconnect
            </Button>
          </div>
          <DisconnectXDialog
            open={confirming}
            handle={connection.handle}
            waiting={counted ? connection.scheduledPostsWaiting : undefined}
            onCancel={() => setConfirming(false)}
            onConfirm={confirmDisconnect}
          />
          {connection.needsReconnect && (
            <div className="flex flex-col gap-3 border-t border-border pt-3 pb-1 sm:flex-row sm:items-center sm:justify-between">
              <p className="font-sans text-sm text-red-700 dark:text-red-300">
                X no longer accepts Pumpkit&apos;s access to @{connection.handle}. Reconnect it to
                keep posting.
              </p>
              <Button className="h-10 shrink-0" disabled={busy} onClick={() => void connect()}>
                {busy ? 'Opening X…' : 'Reconnect X'}
              </Button>
            </div>
          )}
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
