import { useCallback, useEffect, useState } from 'react';
import { errorStatus } from '@/services/apiErrors';
import { briefPosts, briefService, type Brief } from '@/services/briefService';
import { pollDelay } from '@/services/postService';

export type BriefLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; brief: Brief }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

const isWriting = (brief: Brief) =>
  briefPosts(brief).some(({ post }) => post.writingState === 'writing');

/**
 * A Brief with its Ideas and Posts, read again while any Post is being written. Reading stops
 * when the page closes, when none is being written, and on a 404 or 403; a failed read waits
 * longer before the next.
 */
export function useBrief(briefId: string) {
  const [load, setLoad] = useState<BriefLoad>({ kind: 'loading' });

  const loadFailed = useCallback((e: unknown) => {
    if (errorStatus(e) === 404) setLoad({ kind: 'notFound' });
    else setLoad({ kind: 'failed', message: "This brief couldn't be loaded." });
  }, []);

  const reload = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      setLoad({ kind: 'loaded', brief: await briefService.get(briefId) });
    } catch (e) {
      loadFailed(e);
    }
  }, [briefId, loadFailed]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // The writes run on the server whether or not the page is open, so leaving only stops reading.
  const writing = load.kind === 'loaded' && isWriting(load.brief);
  const [poll, setPoll] = useState({ count: 0, failures: 0 });
  useEffect(() => {
    if (!writing) return;
    let stopped = false;
    const timer = setTimeout(() => {
      briefService.get(briefId).then(
        (brief) => {
          if (stopped) return;
          setPoll(({ count }) => ({ count: count + 1, failures: 0 }));
          setLoad({ kind: 'loaded', brief });
        },
        (e: unknown) => {
          if (stopped) return;
          const status = errorStatus(e);
          if (status === 404 || status === 403) loadFailed(e);
          else setPoll(({ count, failures }) => ({ count: count + 1, failures: failures + 1 }));
        },
      );
    }, pollDelay(poll.failures));
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [writing, poll, briefId, loadFailed]);

  return { load, reload };
}
