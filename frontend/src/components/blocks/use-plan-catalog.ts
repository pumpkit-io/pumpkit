import { useEffect, useState } from 'react';
import { billingService, type PlanCatalog } from '@/services/billingService';

export type PlanCatalogState =
  { status: 'loading' } | { status: 'ready'; catalog: PlanCatalog } | { status: 'error' };

/** Fetches the Plan catalogue once for the whole landing page; does nothing where the Instance sells no Plans. */
export function usePlanCatalog(enabled: boolean): PlanCatalogState {
  const [state, setState] = useState<PlanCatalogState>({ status: 'loading' });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    billingService
      .fetchPlans()
      .then((catalog) => !cancelled && setState({ status: 'ready', catalog }))
      .catch(() => !cancelled && setState({ status: 'error' }));
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return state;
}
