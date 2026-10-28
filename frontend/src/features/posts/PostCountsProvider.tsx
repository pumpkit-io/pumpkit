import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { postService, type PostCounts } from '@/services/postService';

interface PostCountsValue {
  /** Null until the first answer, and while none has come. */
  counts: PostCounts | null;
  /** Takes the counts any page of `GET /posts` answered with. */
  setCounts: (counts: PostCounts) => void;
  /** Asks again, after an action that changes a Post's status. */
  refresh: () => void;
}

export const PostCountsContext = createContext<PostCountsValue | null>(null);

/** How many Posts each status holds, shared by the sidebar's Failed badge and the Posts tabs. */
export function PostCountsProvider({ children }: { children: ReactNode }) {
  const [counts, setCounts] = useState<PostCounts | null>(null);

  const refresh = useCallback(() => {
    // One Post is the smallest page; only the counts are read. A failure leaves the last ones.
    postService
      .list('failed', 0, 1)
      .then((page) => setCounts(page.counts))
      .catch(() => undefined);
  }, []);

  useEffect(() => refresh(), [refresh]);

  const value = useMemo(() => ({ counts, setCounts, refresh }), [counts, refresh]);
  return <PostCountsContext.Provider value={value}>{children}</PostCountsContext.Provider>;
}
