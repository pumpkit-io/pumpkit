import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useInstance } from '@/features/instance/useInstance';
import { billingService, type BillingMe, type Plan } from '@/services/billingService';
import { useBilling } from './useBilling';

interface SubscribedContextValue {
  /** Null until the first answer arrives. */
  subscribed: boolean | null;
  /** The name of the Plan the User holds, for the user card; null while unknown or without one. */
  planName: string | null;
  /** Ask the backend again, e.g. after a write was refused with a 403. */
  refresh: () => void;
}

function planNameOf(me: BillingMe, plans: Plan[]): string | null {
  const key = me.subscribed ? me.subscription?.planKey : null;
  return plans.find((plan) => plan.key === key)?.productName ?? null;
}

export const SubscribedContext = createContext<SubscribedContextValue | null>(null);

/**
 * Whether the User is Subscribed, for Home to show writing tools or a prompt to subscribe.
 * It is a hint only: the backend's 403 is the real gate. Must sit inside a BillingProvider.
 * On an Instance that sells no Plans every User counts as Subscribed, so no prompt shows.
 */
export function SubscribedProvider({ children }: { children: ReactNode }) {
  const billing = useBilling();
  const { sells_plans } = useInstance();
  const [subscribed, setSubscribed] = useState<boolean | null>(sells_plans ? null : true);
  const [planName, setPlanName] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!sells_plans) return;
    billingService
      .fetchBillingMe()
      .then(async (me) => {
        setSubscribed(me.subscribed);
        if (!me.subscribed) return setPlanName(null);
        const { plans } = await billingService.fetchPlans();
        setPlanName(planNameOf(me, plans));
      })
      .catch(() => {
        // Leave the last answer: the backend still refuses writes if it was wrong.
      });
  }, [sells_plans]);

  useEffect(refresh, [refresh]);

  // The Billing dialog refetches on every open, after a checkout too: take its answer.
  const billingData = billing.data;
  useEffect(() => {
    if (!billingData) return;
    setSubscribed(billingData.me.subscribed);
    setPlanName(planNameOf(billingData.me, billingData.plans));
  }, [billingData]);

  const value = useMemo(() => ({ subscribed, planName, refresh }), [subscribed, planName, refresh]);
  return <SubscribedContext.Provider value={value}>{children}</SubscribedContext.Provider>;
}
