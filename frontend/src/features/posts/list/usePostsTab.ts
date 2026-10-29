import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage } from '@/services/apiErrors';
import { postService, type PostListItem, type PostStatus } from '@/services/postService';
import { usePostCounts } from '../usePostCounts';

export type PostsTabLoad =
  | { kind: 'loading' }
  | { kind: 'failed'; message: string }
  | {
      kind: 'loaded';
      posts: PostListItem[];
      nextOffset: number | null;
      /** Show more: 'loading' while the next page comes, 'failed' when it didn't. */
      more: 'idle' | 'loading' | 'failed';
    };

/**
 * The Posts of one tab, a page at a time. Every page's counts go to the sidebar's badge and the
 * tab labels, so they agree with the list on screen.
 */
export function usePostsTab(status: PostStatus) {
  const { setCounts } = usePostCounts();
  const [load, setLoad] = useState<PostsTabLoad>({ kind: 'loading' });
  // A page that answers after the tab was left must not land in it.
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const loadFirst = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      const page = await postService.list(status);
      if (!live.current) return;
      setCounts(page.counts);
      setLoad({ kind: 'loaded', posts: page.posts, nextOffset: page.nextOffset, more: 'idle' });
    } catch (e) {
      if (live.current) {
        setLoad({ kind: 'failed', message: errorMessage(e, "Couldn't load your Posts.") });
      }
    }
  }, [status, setCounts]);

  useEffect(() => {
    void loadFirst();
  }, [loadFirst]);

  const showMore = useCallback(async () => {
    if (load.kind !== 'loaded' || load.nextOffset === null || load.more === 'loading') return;
    const shown = load;
    setLoad({ ...shown, more: 'loading' });
    try {
      const page = await postService.list(status, shown.nextOffset!);
      if (!live.current) return;
      setCounts(page.counts);
      setLoad({
        kind: 'loaded',
        // A Post can move between pages while the User reads; keep each one once.
        posts: [
          ...shown.posts,
          ...page.posts.filter((p) => !shown.posts.some((s) => s.id === p.id)),
        ],
        nextOffset: page.nextOffset,
        more: 'idle',
      });
    } catch {
      if (live.current) setLoad({ ...shown, more: 'failed' });
    }
  }, [load, status, setCounts]);

  return { load, retry: loadFirst, showMore };
}
