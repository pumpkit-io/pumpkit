import { Button } from '@/components/ui/button';
import { useXConnectionContext } from './useXConnectionContext';

/** Across the top of every page while X no longer accepts the X connection. */
export function ReconnectXBanner() {
  const { connection, busy, error, connect } = useXConnectionContext();
  if (!connection?.needsReconnect) return null;

  return (
    <section
      aria-label="Reconnect X"
      className="flex shrink-0 flex-col gap-2 border-b border-destructive/40 bg-destructive/10 px-4 py-2.5 sm:flex-row sm:items-center sm:gap-4 sm:px-6"
    >
      <div className="min-w-0 flex-1 font-sans text-sm text-foreground">
        <p>
          <span className="font-medium text-destructive">
            X no longer accepts Pumpkit&apos;s access to @{connection.handle}.
          </span>{' '}
          Scheduled posts won&apos;t go out until you reconnect.
        </p>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
      <Button
        size="sm"
        className="h-9 shrink-0 self-start sm:self-auto"
        disabled={busy}
        onClick={() => void connect()}
      >
        {busy ? 'Opening X…' : 'Reconnect X'}
      </Button>
    </section>
  );
}
