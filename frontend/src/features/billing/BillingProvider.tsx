import { createContext, useCallback, useMemo, useState, type ReactNode } from 'react';
import { billingService, type BillingMe, type Plan } from '@/services/billingService';

export interface BillingData {
  me: BillingMe;
  plans: Plan[];
  termsVersion: string | null;
}

interface BillingContextValue {
  data: BillingData | null;
  isLoading: boolean;
  /** Why the last load failed, or null. */
  loadError: string | null;
  load: () => Promise<void>;
}

export const BillingContext = createContext<BillingContextValue | null>(null);

/** The User's Subscription and the Plans on sale, for the Settings cards and the user card. */
export function BillingProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<BillingData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const [me, { plans, termsVersion }] = await Promise.all([
        billingService.fetchBillingMe(),
        billingService.fetchPlans(),
      ]);
      setData({ me, plans, termsVersion });
    } catch {
      setLoadError('Could not load billing information. Reload the page to try again.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const value = useMemo<BillingContextValue>(
    () => ({ data, isLoading, loadError, load }),
    [data, isLoading, loadError, load],
  );

  return <BillingContext.Provider value={value}>{children}</BillingContext.Provider>;
}
