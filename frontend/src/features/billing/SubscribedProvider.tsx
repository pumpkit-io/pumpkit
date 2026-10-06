import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { billingService } from '@/services/billingService';
import { useBilling } from './useBilling';

interface SubscribedContextValue {
  /** Null until the first answer arrives. */
  subscribed: boolean | null;
  /** Ask the backend again, e.g. after a write was refused with a 403. */
  refresh: () => void;
}

export const SubscribedContext = createContext<SubscribedContextValue | null>(null);

/**
 * Whether the User is Subscribed, for Home to show writing tools or a prompt to subscribe.
 * It is a hint only: the backend's 403 is the real gate. Must sit inside a BillingProvider.
 */
export function SubscribedProvider({ children }: { children: ReactNode }) {
  const billing = useBilling();
  const [subscribed, setSubscribed] = useState<boolean | null>(null);

  const refresh = useCallback(() => {
    billingService
      .fetchBillingMe()
      .then((me) => setSubscribed(me.subscribed))
      .catch(() => {
        // Leave the last answer: the backend still refuses writes if it was wrong.
      });
  }, []);

  useEffect(refresh, [refresh]);

  // The Billing dialog refetches on every open, after a checkout too: take its answer.
  const billingSubscribed = billing.data?.me.subscribed;
  useEffect(() => {
    if (billingSubscribed !== undefined) setSubscribed(billingSubscribed);
  }, [billingSubscribed]);

  const value = useMemo(() => ({ subscribed, refresh }), [subscribed, refresh]);
  return <SubscribedContext.Provider value={value}>{children}</SubscribedContext.Provider>;
}
