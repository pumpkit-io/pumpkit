import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { useInstance } from '@/features/instance/useInstance';
import { useXConnectionContext } from './useXConnectionContext';

/** Restores publishing authorization for the account the User signed in with. */
export function ConnectXPrompt({ what, showError }: { what?: string; showError?: boolean }) {
  const { busy, error, connect } = useXConnectionContext();
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
        <p className="font-sans text-sm text-foreground">{`Reconnect X to post${target}.`}</p>
        <Button
          type="button"
          size="sm"
          className="h-11 min-w-11 shrink-0"
          disabled={busy}
          onClick={() => void connect()}
        >
          Reconnect X
        </Button>
      </div>
      {showError && error && <ErrorBanner message={error} />}
    </div>
  );
}
