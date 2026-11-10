import { useEffect, useRef } from 'react';
import { PersonaStep } from '@/features/onboarding/PersonaStep';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { track } from '@/lib/analytics';

export function Onboarding() {
  const { state } = useOnboarding();
  const viewed = useRef(false);
  const step = state.status === 'ready' ? state.nextStep : null;
  useEffect(() => {
    if (step !== 'persona' || viewed.current) return;
    viewed.current = true;
    track('onboarding_step_viewed', { step });
  }, [step]);
  return step === 'persona' ? <PersonaStep /> : null;
}
