import { createContext, useCallback, useMemo, useState, type ReactNode } from 'react';
import { billingService, errorMessage, type BillingMe, type Plan } from '@/services/billingService';
import { track } from '@/lib/analytics';

export interface BillingData {
  me: BillingMe;
  plans: Plan[];
}

interface BillingContextValue {
  isOpen: boolean;
  error: string | null;
  data: BillingData | null;
  isLoading: boolean;
  open: (source?: string) => void;
  openWithError: (message: string, source?: string) => void;
  close: () => void;
}

export const BillingContext = createContext<BillingContextValue | null>(null);

export function BillingProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<BillingData | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Billing state changes outside the app (Stripe), so refetch on every open.
  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const [me, plans] = await Promise.all([
        billingService.fetchBillingMe(),
        billingService.fetchPlans(),
      ]);
      setData({ me, plans });
    } catch (e) {
      setError(errorMessage(e, 'Could not load billing information.'));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const openInternal = useCallback(
    (message: string | null, source?: string) => {
      setError(message);
      setIsOpen(true);
      track('billing_dialog_opened', { source: source ?? 'unknown' });
      void load();
    },
    [load],
  );

  const open = useCallback((source?: string) => openInternal(null, source), [openInternal]);
  const openWithError = useCallback(
    (message: string, source?: string) => openInternal(message, source),
    [openInternal],
  );
  const close = useCallback(() => {
    setIsOpen(false);
    setError(null);
    track('billing_dialog_closed');
  }, []);

  const value = useMemo<BillingContextValue>(
    () => ({ isOpen, error, data, isLoading, open, openWithError, close }),
    [isOpen, error, data, isLoading, open, openWithError, close],
  );

  return <BillingContext.Provider value={value}>{children}</BillingContext.Provider>;
}
