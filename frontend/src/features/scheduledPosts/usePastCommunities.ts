import { useEffect, useState } from 'react';
import { scheduledPostService, type Community } from '@/services/scheduledPostService';

const changes = new EventTarget();

/** Reloads every mounted past Communities list, after a post went into a Community. */
export function pastCommunitiesChanged() {
  changes.dispatchEvent(new Event('change'));
}

/** The Communities the User posted to before; without them, pasting a Community still works. */
export function usePastCommunities(): Community[] {
  const [past, setPast] = useState<Community[]>([]);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      scheduledPostService
        .pastCommunities()
        .then((found) => !cancelled && setPast(found))
        .catch(() => undefined);
    };
    load();
    changes.addEventListener('change', load);
    return () => {
      cancelled = true;
      changes.removeEventListener('change', load);
    };
  }, []);
  return past;
}
