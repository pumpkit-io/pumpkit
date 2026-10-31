import type { NextStep } from '@/services/onboardingService';

/** Where a User past the Paywall and Onboarding lands. */
export const APP_HOME = '/new';
export const PAYWALL_PATH = '/subscribe';
export const ONBOARDING_PATH = '/onboarding';

/** The page that serves `nextStep`: the URL never names a step, the backend's answer does. */
export function pathFor(nextStep: NextStep | null): string {
  if (nextStep === 'paywall') return PAYWALL_PATH;
  if (nextStep === null) return APP_HOME;
  return ONBOARDING_PATH;
}
