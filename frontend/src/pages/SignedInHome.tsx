import { useEffect, useRef, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { checkoutStatusOf, type CheckoutArrival } from '@/features/billing/checkoutArrival';
import { pathFor } from '@/features/onboarding/paths';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { track } from '@/lib/analytics';
import { fireSuccessConfetti } from '@/lib/confetti';

// Stripe's webhook can land a moment after the success redirect, so `/` asks again a few times.
const CONFIRM_ATTEMPTS = 5;
const CONFIRM_INTERVAL_MS = 1000;

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

/** Greets a return from checkout once, as StrictMode runs effects twice in development. */
function useCheckoutGreeting(status: CheckoutArrival['checkoutStatus']) {
  const greeted = useRef(false);
  useEffect(() => {
    if (greeted.current) return;
    greeted.current = true;
    if (status === 'success') {
      track('billing_checkout_succeeded');
      fireSuccessConfetti(null);
    } else if (status === 'cancelled') {
      track('billing_checkout_cancelled');
    }
  }, [status]);
}

/** Whether `/` is still waiting for a checkout's Subscription to reach Pumpkit's copy. */
function useConfirmingSubscription(status: CheckoutArrival['checkoutStatus']): boolean {
  const { state, refresh } = useOnboarding();
  const [confirming, setConfirming] = useState(status === 'success');
  const loaded = state.status !== 'loading';
  const atPaywall = state.status === 'ready' && state.nextStep === 'paywall';

  useEffect(() => {
    if (!confirming || !loaded) return;
    if (!atPaywall) {
      setConfirming(false);
      return;
    }
    let cancelled = false;
    void (async () => {
      for (let attempt = 0; attempt < CONFIRM_ATTEMPTS; attempt += 1) {
        await wait(CONFIRM_INTERVAL_MS);
        if (cancelled) return;
        // Past the Paywall, `atPaywall` turns false and this effect ends the wait.
        if ((await refresh()) === null) return;
      }
      if (!cancelled) setConfirming(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [confirming, loaded, atPaywall, refresh]);

  return confirming;
}

/** `/` for a signed-in User: the page their next step is on, after greeting a checkout. */
export function SignedInHome() {
  const { state } = useOnboarding();
  const location = useLocation();
  const [status] = useState(() => checkoutStatusOf(location.state));
  useCheckoutGreeting(status);
  const confirming = useConfirmingSubscription(status);

  if (state.status === 'loading' || confirming) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-background text-foreground">
        <p role="status" className="font-sans text-sm text-muted-foreground">
          {status === 'success' ? 'Confirming your subscription…' : 'Loading…'}
        </p>
      </div>
    );
  }
  const arrival: CheckoutArrival | null = status ? { checkoutStatus: status } : null;
  const nextStep = state.status === 'ready' ? state.nextStep : null;
  return <Navigate to={pathFor(nextStep)} replace state={arrival} />;
}
