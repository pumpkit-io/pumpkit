import { useContext, useEffect, useRef } from 'react';
import { BillingContext } from './BillingProvider';

export function useBilling() {
  const ctx = useContext(BillingContext);
  if (!ctx) {
    throw new Error('useBilling must be used within a BillingProvider');
  }
  return ctx;
}

/**
 * `useBilling`, loading billing while `enabled` where nothing has yet, such as away from
 * Settings. It tries once each time `enabled` turns on, so a failed load isn't retried in a loop.
 */
export function useLoadedBilling(enabled = true) {
  const billing = useBilling();
  const { data, isLoading, load } = billing;
  const tried = useRef(false);

  useEffect(() => {
    if (!enabled) {
      tried.current = false;
      return;
    }
    if (tried.current || data || isLoading) return;
    tried.current = true;
    void load();
  }, [enabled, data, isLoading, load]);

  return billing;
}
