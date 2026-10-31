import { useCallback, useEffect, useRef, useState } from 'react';
import { usageService, type Usage } from '@/services/usageService';

/** How long a chosen moment stays unchanged before its period loads, so typing a time asks once. */
const AT_SETTLE_MS = 300;

export interface UsageState {
  /** Null until it loads; a failed reload keeps the last one. */
  usage: Usage | null;
  failed: boolean;
  /** Load it again, such as after an action used some of the Allowance. */
  reload: () => void;
}

/**
 * What the User has left of the Allowance period holding `at` (an ISO instant), or now without
 * one. It loads on mount and again once a changed `at` settles; only the latest answer shows.
 */
export function useUsage(at?: string | null): UsageState {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [failed, setFailed] = useState(false);
  const mounted = useRef(true);
  const latest = useRef(0);

  const reload = useCallback(() => {
    const request = ++latest.current;
    const current = () => mounted.current && request === latest.current;
    usageService
      .get(at ?? undefined)
      .then((loaded) => {
        if (!current()) return;
        setUsage(loaded);
        setFailed(false);
      })
      .catch(() => current() && setFailed(true));
  }, [at]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!at) {
      reload();
      return;
    }
    const timer = setTimeout(reload, AT_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [at, reload]);

  return { usage, failed, reload };
}
