import { useEffect, useId, useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { UserAvatar } from '@/components/UserAvatar';
import { Button } from '@/components/ui/button';
import { redirectTo } from '@/lib/navigation';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { xConnectionService } from '@/services/xConnectionService';
import type { XConnectionArrival } from './paths';
import { useOnboarding } from './useOnboarding';

const TAKEN = 'That X account is connected to another Pumpkit account.';

function arrivalError(arrival: XConnectionArrival | undefined): string | null {
  if (arrival?.outcome === 'taken') return TAKEN;
  if (arrival?.outcome === 'failed') return arrival.reason;
  return null;
}

/** Asks the backend again whenever the tab comes back, as X may have been connected in another. */
function useRefreshOnReturn() {
  const { refresh } = useOnboarding();
  useEffect(() => {
    const onReturn = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    window.addEventListener('focus', onReturn);
    document.addEventListener('visibilitychange', onReturn);
    return () => {
      window.removeEventListener('focus', onReturn);
      document.removeEventListener('visibilitychange', onReturn);
    };
  }, [refresh]);
}

/** Onboarding's X step: one action, which leaves for X's consent screen and comes back here. */
export function XStep({ arrival }: { arrival?: XConnectionArrival }) {
  const headingId = useId();
  const { refresh } = useOnboarding();
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(() => arrivalError(arrival));
  useRefreshOnReturn();

  const connect = async () => {
    setOpening(true);
    setError(null);
    try {
      redirectTo(await xConnectionService.startAuthorization());
    } catch (e) {
      setOpening(false);
      if (errorStatus(e) === 403) void refresh();
      else setError(errorMessage(e, "Couldn't start connecting X. Try again."));
    }
  };

  return (
    <section aria-labelledby={headingId} className="max-w-[560px] space-y-5">
      <div className="space-y-1">
        <h1
          id={headingId}
          className="font-sans text-2xl/[30px] font-semibold tracking-[-0.015em] text-foreground"
        >
          Connect your X account
        </h1>
        <p className="font-sans text-sm text-muted-foreground">
          Pumpkit publishes your posts from this account.
        </p>
      </div>
      {error && <ErrorBanner message={error} />}
      <div className="space-y-2">
        <Button type="button" className="h-10" disabled={opening} onClick={() => void connect()}>
          {opening ? 'Opening X…' : error ? 'Try again' : 'Connect X'}
        </Button>
        <p className="font-sans text-sm text-muted-foreground">
          You&apos;ll approve access on X, then come back here.
        </p>
      </div>
    </section>
  );
}

/** The account just connected, shown for a moment so the User knows which one it was. */
export function XConnected({ handle, photoUrl }: { handle: string; photoUrl: string | null }) {
  return (
    <div
      role="status"
      aria-label="X connected"
      className="flex max-w-[560px] items-center gap-4 motion-safe:animate-in motion-safe:fade-in"
    >
      <UserAvatar name={handle} avatarUrl={photoUrl} className="h-14 w-14 text-base" />
      <div className="min-w-0">
        <p className="font-sans text-sm text-muted-foreground">Connected</p>
        <p className="truncate font-sans text-xl font-semibold text-foreground">@{handle}</p>
      </div>
    </div>
  );
}
