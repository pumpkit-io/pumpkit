import { useCallback, useEffect, useRef, useState } from 'react';
import { usageService, type Usage } from '@/services/usageService';

export interface UsageState {
  /** Null until it loads; a failed reload keeps the last one. */
  usage: Usage | null;
  /** Whether the last load failed. */
  failed: boolean;
  /** Load it again, such as after an action used some of the Allowance. */
  reload: () => void;
}

/** What the User has left of their Allowance, loaded when the component mounts. */
export function useUsage(): UsageState {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [failed, setFailed] = useState(false);
  const mounted = useRef(true);

  const reload = useCallback(() => {
    usageService
      .get()
      .then((loaded) => {
        if (!mounted.current) return;
        setUsage(loaded);
        setFailed(false);
      })
      .catch(() => mounted.current && setFailed(true));
  }, []);

  useEffect(() => {
    mounted.current = true;
    reload();
    return () => {
      mounted.current = false;
    };
  }, [reload]);

  return { usage, failed, reload };
}
