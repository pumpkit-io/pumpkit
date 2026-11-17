import { createContext, useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { billingService, type BillingMe, type PlanCatalog } from '@/services/billingService';

export interface BillingData extends PlanCatalog {
  me: BillingMe;
}

interface BillingContextValue {
  data: BillingData | null;
  isLoading: boolean;
  /** Why the last load failed, or null. */
  loadError: string | null;
  load: () => Promise<void>;
  isOpeningPortal: boolean;
  requestPortal: () => Promise<string | null>;
}

export const BillingContext = createContext<BillingContextValue | null>(null);

/** The User's Subscription and the Plans on sale, for the Settings cards and the user card. */
export function BillingProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<BillingData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [isOpeningPortal, setIsOpeningPortal] = useState(false);
  const requestingPortal = useRef(false);

  const requestPortal = useCallback(async () => {
    if (requestingPortal.current) return null;
    requestingPortal.current = true;
    setIsOpeningPortal(true);
    try {
      return await billingService.openBillingPortal();
    } finally {
      requestingPortal.current = false;
      setIsOpeningPortal(false);
    }
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const [me, catalog] = await Promise.all([
        billingService.fetchBillingMe(),
        billingService.fetchPlans(),
      ]);
      setData({ me, ...catalog });
    } catch {
      setLoadError("Couldn't load billing information. Reload the page to try again.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const value = useMemo<BillingContextValue>(
    () => ({ data, isLoading, loadError, load, isOpeningPortal, requestPortal }),
    [data, isLoading, loadError, load, isOpeningPortal, requestPortal],
  );

  return <BillingContext.Provider value={value}>{children}</BillingContext.Provider>;
}
