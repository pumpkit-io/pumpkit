import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { useXConnectionContext } from './useXConnectionContext';

/**
 * Asks the User to connect X, or to reconnect it once X stopped accepting Pumpkit's access.
 * `what` names what they are about to post, as in "this Final".
 */
export function ConnectXPrompt({ what, showError }: { what?: string; showError?: boolean }) {
  const { connection, busy, error, connect } = useXConnectionContext();
  const target = what ? ` ${what}` : '';
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
