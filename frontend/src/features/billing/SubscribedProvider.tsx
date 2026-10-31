import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useInstance } from '@/features/instance/useInstance';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { billingService, type BillingMe, type Plan } from '@/services/billingService';
import { useBilling } from './useBilling';

interface SubscribedContextValue {
  /** The name of the Plan the User holds, for the user card; null while unknown or without one. */
  planName: string | null;
  /** Checks the Paywall again after a 403, so a User whose Subscription ended is sent to it. */
  refresh: () => void;
}

function planNameOf(me: BillingMe, plans: Plan[]): string | null {
  const key = me.subscribed ? me.subscription?.planKey : null;
  return plans.find((plan) => plan.key === key)?.productName ?? null;
}

export const SubscribedContext = createContext<SubscribedContextValue | null>(null);

/**
 * The Subscribed User's Plan, inside the Paywall's gate, where every User is Subscribed or the
 * Instance sells no Plans. Must sit inside a BillingProvider and an OnboardingProvider.
 */
export function SubscribedProvider({ children }: { children: ReactNode }) {
  const billing = useBilling();
  const { sells_plans } = useInstance();
  const { refresh: refreshOnboarding } = useOnboarding();
  const [planName, setPlanName] = useState<string | null>(null);

  const loadPlanName = useCallback(() => {
    if (!sells_plans) return;
    Promise.all([billingService.fetchBillingMe(), billingService.fetchPlans()])
      .then(([me, { plans }]) => setPlanName(planNameOf(me, plans)))
      .catch(() => {
        // The user card shows "Subscribed" without the Plan's name.
      });
  }, [sells_plans]);

  useEffect(loadPlanName, [loadPlanName]);

  // Settings reloads billing on every visit: take its answer.
  const billingData = billing.data;
  useEffect(() => {
    if (billingData) setPlanName(planNameOf(billingData.me, billingData.plans));
  }, [billingData]);

  const refresh = useCallback(() => void refreshOnboarding(), [refreshOnboarding]);

  const value = useMemo(() => ({ planName, refresh }), [planName, refresh]);
  return <SubscribedContext.Provider value={value}>{children}</SubscribedContext.Provider>;
}
