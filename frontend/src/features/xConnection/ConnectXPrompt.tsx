import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { useInstance } from '@/features/instance/useInstance';
import { useXConnectionContext } from './useXConnectionContext';

/**
 * Asks the User to connect X, or to reconnect it once X stopped accepting Pumpkit's access,
 * and only says posting to X isn't set up on an Instance without X's app keys.
 * `what` names what they are about to post, as in "this Post".
 */
export function ConnectXPrompt({ what, showError }: { what?: string; showError?: boolean }) {
  const { connection, busy, error, connect } = useXConnectionContext();
  const { x_connection } = useInstance();
  const target = what ? ` ${what}` : '';
  if (!x_connection) {
    return (
      <p className="font-sans text-sm text-foreground">
        Posting to X isn&apos;t set up on this Pumpkit yet.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="font-sans text-sm text-foreground">
          {connection
            ? `Reconnect X to post${target}.`
            : `Connect your X account to post${target}.`}
        </p>
        <Button
          type="button"
          size="sm"
          className="h-10 shrink-0"
          disabled={busy}
          onClick={() => void connect()}
        >
          {connection ? 'Reconnect X' : 'Connect X'}
        </Button>
      </div>
      {showError && error && <ErrorBanner message={error} />}
    </div>
  );
}
