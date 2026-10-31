import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { pathFor } from './paths';
import { useOnboarding } from './useOnboarding';

function FullPage({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-3 bg-background px-4 text-foreground">
      {children}
    </div>
  );
}

/**
 * Renders `children` only where the User's next step is served from `home`, and sends them to
 * the page that serves it otherwise, keeping the location state, so a stale tab corrects itself.
 */
export function OnboardingGate({ home, children }: { home: string; children: ReactNode }) {
  const { state, refresh } = useOnboarding();
  const location = useLocation();

  if (state.status === 'loading') {
    return (
      <FullPage>
        <p role="status" className="font-sans text-sm text-muted-foreground">
          Loading…
        </p>
      </FullPage>
    );
  }
  if (state.status === 'failed') {
    return (
      <FullPage>
        <p role="alert" className="font-sans text-sm text-foreground">
          Couldn&apos;t load your account.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={() => void refresh()}>
          Try again
        </Button>
      </FullPage>
    );
  }
  const target = pathFor(state.nextStep);
  if (target !== home) return <Navigate to={target} replace state={location.state} />;
  return <>{children}</>;
}
