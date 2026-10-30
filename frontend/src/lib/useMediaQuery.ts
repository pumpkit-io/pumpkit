import { useEffect, useState } from 'react';

/** Below Tailwind's `sm` breakpoint. */
export const PHONE = '(max-width: 639px)';

/** Whether `query` matches now, following the window as it changes. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}
