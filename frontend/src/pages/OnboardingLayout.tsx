import { Outlet } from 'react-router-dom';
import { StepIndicator } from '@/features/onboarding/StepIndicator';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { FocusedLayout } from './FocusedLayout';

/** The focused shell of the Paywall and Onboarding, with the steps before Pumpkit opens. */
export function OnboardingLayout() {
  const { state } = useOnboarding();
  const current = state.status === 'ready' ? state.nextStep : null;

  return (
    <FocusedLayout header={current && <StepIndicator current={current} />}>
      <Outlet />
    </FocusedLayout>
  );
}
