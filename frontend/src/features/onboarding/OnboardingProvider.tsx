import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { onboardingService, type NextStep } from '@/services/onboardingService';

export type OnboardingState =
  { status: 'loading' } | { status: 'failed' } | { status: 'ready'; nextStep: NextStep | null };

interface OnboardingContextValue {
  state: OnboardingState;
  /** Asks the backend again, e.g. after a 403 or a checkout, and resolves with its answer. */
  refresh: () => Promise<NextStep | null | undefined>;
}

export const OnboardingContext = createContext<OnboardingContextValue | null>(null);

/**
 * Where the signed-in User goes next, read on every sign-in and page load, since the Paywall is
 * checked on every visit (ADR 0018). Page tests pass `initialNextStep` to start without a fetch.
 */
export function OnboardingProvider({
  initialNextStep,
  children,
}: {
  initialNextStep?: NextStep | null;
  children: ReactNode;
}) {
  const { isAuthenticated } = useAuth();
  const fetchOnSignIn = initialNextStep === undefined;
  const [state, setState] = useState<OnboardingState>(
    fetchOnSignIn ? { status: 'loading' } : { status: 'ready', nextStep: initialNextStep },
  );

  const refresh = useCallback(async () => {
    try {
      const nextStep = await onboardingService.fetchNextStep();
      setState({ status: 'ready', nextStep });
      return nextStep;
    } catch {
      // A failed check keeps the last answer: the backend still refuses a User it was wrong about.
      setState((current) => (current.status === 'ready' ? current : { status: 'failed' }));
      return undefined;
    }
  }, []);

  useEffect(() => {
    if (!fetchOnSignIn) return;
    if (isAuthenticated) void refresh();
    else setState({ status: 'loading' });
  }, [fetchOnSignIn, isAuthenticated, refresh]);

  const value = useMemo(() => ({ state, refresh }), [state, refresh]);
  return <OnboardingContext.Provider value={value}>{children}</OnboardingContext.Provider>;
}
