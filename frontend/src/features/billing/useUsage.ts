import { useEffect, useState } from 'react';
import { usageService, type Usage } from '@/services/usageService';

/** What the User has left of their Allowance, null until it loads; a failed load stays null. */
export function useUsage(): Usage | null {
  const [usage, setUsage] = useState<Usage | null>(null);
  useEffect(() => {
    let cancelled = false;
    usageService
      .get()
      .then((loaded) => !cancelled && setUsage(loaded))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  return usage;
}
