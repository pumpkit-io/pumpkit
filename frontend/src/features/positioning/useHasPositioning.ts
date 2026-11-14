import { useEffect, useState } from 'react';
import { positioningService } from '@/services/positioningService';

/**
 * Whether the User has saved a Positioning, which planning a Brief needs; null until it is
 * read. A failed read counts as having one: the backend then refuses with the reason.
 */
export function useHasPositioning(): boolean | null {
  const [has, setHas] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    positioningService
      .get()
      .then((positioning) => !cancelled && setHas(positioning.text !== null))
      .catch(() => !cancelled && setHas(true));
    return () => {
      cancelled = true;
    };
  }, []);
  return has;
}
