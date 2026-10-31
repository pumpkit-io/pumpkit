import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { OnboardingLocationState, XConnectionArrival } from '@/features/onboarding/paths';
import { PersonaStep } from '@/features/onboarding/PersonaStep';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { XConnected, XStep } from '@/features/onboarding/XStep';
import { track } from '@/lib/analytics';

/** How long the connected X account shows before the next step. */
const X_CONNECTED_MS = 1500;

/** Tracks each step once as it first shows, as StrictMode runs effects twice in development. */
function useStepViewed(step: string | null) {
  const viewed = useRef<string | null>(null);
  useEffect(() => {
    if (!step || viewed.current === step) return;
    viewed.current = step;
    track('onboarding_step_viewed', { step });
  }, [step]);
}

/** Takes what the X callback left once, then drops it so a reload doesn't show it again. */
function useXArrival(): XConnectionArrival | undefined {
  const location = useLocation();
  const navigate = useNavigate();
  const [arrival] = useState(() => (location.state as OnboardingLocationState | null)?.xConnection);

  useEffect(() => {
    if (arrival) navigate('.', { replace: true, state: null });
  }, [arrival, navigate]);

  return arrival;
}

/** True for a moment after X was connected, while the connected account shows. */
function useShowingConnected(arrival: XConnectionArrival | undefined): boolean {
  const [showing, setShowing] = useState(arrival?.outcome === 'connected');
  useEffect(() => {
    if (!showing) return;
    const timer = setTimeout(() => setShowing(false), X_CONNECTED_MS);
    return () => clearTimeout(timer);
  }, [showing]);
  return showing;
}

/** `/onboarding`: the step the backend names, never one named in the URL (ADR 0018). */
export function Onboarding() {
  const { state } = useOnboarding();
  const arrival = useXArrival();
  const showingConnected = useShowingConnected(arrival);
  const step = state.status === 'ready' && !showingConnected ? state.nextStep : null;
  useStepViewed(step);

  if (showingConnected && arrival?.outcome === 'connected') {
    return <XConnected handle={arrival.handle} photoUrl={arrival.photoUrl} />;
  }
  if (step === 'x_connection') return <XStep arrival={arrival} />;
  return step === 'persona' ? <PersonaStep /> : null;
}
