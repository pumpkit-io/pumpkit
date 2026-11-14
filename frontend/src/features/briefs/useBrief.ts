import { useCallback, useEffect, useState } from 'react';
import { errorStatus } from '@/services/apiErrors';
import { briefPosts, briefService, type Brief } from '@/services/briefService';
import { useReadWhileWriting } from '@/features/posts/useReadWhileWriting';

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
  const readBrief = useCallback(() => briefService.get(briefId), [briefId]);
  const show = useCallback((brief: Brief) => setLoad({ kind: 'loaded', brief }), []);
  useReadWhileWriting(writing, readBrief, show, loadFailed);

  return { load, reload };
}
