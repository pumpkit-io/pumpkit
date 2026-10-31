import type { NextStep } from '@/services/onboardingService';

/** Where a User past the Paywall and Onboarding lands. */
export const APP_HOME = '/new';
export const PAYWALL_PATH = '/subscribe';

/** The page that serves `nextStep`: the URL never names a step, the backend's answer does. */
export function pathFor(nextStep: NextStep | null): string {
  return nextStep === 'paywall' ? PAYWALL_PATH : APP_HOME;
}
