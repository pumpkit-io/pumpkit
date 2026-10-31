import { useCallback, useState } from 'react';
import { track } from '@/lib/analytics';
import { errorAllowanceUsedUp, type AllowanceUsedUp } from '@/services/apiErrors';

/**
 * The Allowance refusal a request last failed with, shown with its way out rather than as an
 * error. `caught` records and tracks one, and says whether `e` was one.
 */
export function useAllowanceUsedUp() {
  const [allowanceUsedUp, setAllowanceUsedUp] = useState<AllowanceUsedUp | null>(null);

  const caught = useCallback((e: unknown): boolean => {
    const usedUp = errorAllowanceUsedUp(e);
    if (!usedUp) return false;
    track('allowance_used_up', { ran_out: usedUp.ranOut });
    setAllowanceUsedUp(usedUp);
    return true;
  }, []);

  const clear = useCallback(() => setAllowanceUsedUp(null), []);

  return { allowanceUsedUp, caught, clear };
}
