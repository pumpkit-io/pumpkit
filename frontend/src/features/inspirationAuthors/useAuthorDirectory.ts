import { useEffect, useState } from 'react';
import {
  authorDirectoryService,
  type AuthorDirectoryEntry,
} from '@/services/authorDirectoryService';

/** The whole Author directory, loaded once on mount; null while it loads. */
export function useAuthorDirectory() {
  const [entries, setEntries] = useState<AuthorDirectoryEntry[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authorDirectoryService
      .list()
      .then((list) => !cancelled && setEntries(list))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  return { entries, failed };
}
