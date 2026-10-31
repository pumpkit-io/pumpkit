import { useEffect, useRef } from 'react';
import { PersonaStep } from '@/features/onboarding/PersonaStep';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { track } from '@/lib/analytics';

/** Tracks each step once as it first shows, as StrictMode runs effects twice in development. */
function useStepViewed(step: string | null) {
  const viewed = useRef<string | null>(null);
  useEffect(() => {
    if (!step || viewed.current === step) return;
    viewed.current = step;
    track('onboarding_step_viewed', { step });
  }, [step]);
}

/** `/onboarding`: the step the backend names, never one named in the URL (ADR 0018). */
export function Onboarding() {
  const { state } = useOnboarding();
  const step = state.status === 'ready' ? state.nextStep : null;
  useStepViewed(step);

  return step === 'persona' ? <PersonaStep /> : null;
}
