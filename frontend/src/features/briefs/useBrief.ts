import { useCallback, useEffect, useState } from 'react';
import { track } from '@/lib/analytics';
import {
  errorAllowanceUsedUp,
  errorCode,
  errorStatus,
  type AllowanceUsedUp,
} from '@/services/apiErrors';
import { briefPosts, briefService, type Brief } from '@/services/briefService';
import { postService } from '@/services/postService';
import { useReadWhileWriting } from '@/features/posts/useReadWhileWriting';
import { useWritingFailure } from '@/features/posts/useWritingFailure';

export type BriefLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; brief: Brief }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

/** Why asking to write the Idea `ideaId`, or to retry its Post, failed. */
export interface BriefFailure {
  ideaId: string;
  error: string | null;
  notice: string | null;
  allowanceUsedUp: AllowanceUsedUp | null;
}

const isWriting = (brief: Brief) =>
  briefPosts(brief).some(({ post }) => post.writingState === 'writing');

/** A 409 that may mean the Post or Idea moved on elsewhere, so reading the Brief again settles it. */
const movedOn = (e: unknown) => errorStatus(e) === 409 && !errorAllowanceUsedUp(e);

/**
 * A Brief with its Ideas and Posts, read again while any Post is being written. Reading stops
 * when the page closes, when none is being written, and on a 404 or 403; a failed read waits
 * longer before the next. `write` and `retry` start a Post's write and read the Brief again; why
 * one failed goes with the Idea it was asked for, in `failure`.
 */
export function useBrief(briefId: string) {
  const [load, setLoad] = useState<BriefLoad>({ kind: 'loading' });
  // The Idea whose write is being asked for, then the one whose request failed.
  const [busyIdea, setBusyIdea] = useState<string | null>(null);
  const [failedIdea, setFailedIdea] = useState<string | null>(null);
  const { error, notice, allowanceUsedUp, fail, clear } = useWritingFailure();

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

  /** Reads the Brief in place, without the loading state. */
  const refresh = useCallback(async () => {
    try {
      show(await readBrief());
    } catch (e) {
      loadFailed(e);
    }
  }, [readBrief, show, loadFailed]);

  const act = useCallback(
    async (ideaId: string, request: () => Promise<unknown>, onFailure: (e: unknown) => boolean) => {
      clear();
      setFailedIdea(null);
      setBusyIdea(ideaId);
      try {
        await request();
        await refresh();
      } catch (e) {
        if (onFailure(e)) await refresh();
        else setFailedIdea(ideaId);
      } finally {
        setBusyIdea(null);
      }
    },
    [clear, refresh],
  );

  /** Writes an Idea not written yet, from the Plan it already has. */
  const write = useCallback(
    (ideaId: string) => {
      track('post_version_requested', { kind: 'brief' });
      return act(
        ideaId,
        () => briefService.write(briefId, [ideaId]),
        (e) => {
          // An earlier request wrote it and its answer was lost: the Brief now shows its Post.
          if (errorCode(e) === 'IDEAS_ALREADY_WRITTEN') return true;
          fail(e, "Couldn't start writing this post. Try again.");
          return false;
        },
      );
    },
    [act, briefId, fail],
  );

  /** Writes a Post's first Version again, after Pumpkit couldn't write it. */
  const retry = useCallback(
    (ideaId: string, postId: string) => {
      track('post_version_requested', { kind: 'retry' });
      return act(
        ideaId,
        () => postService.retry(postId),
        (e) => {
          // Written late, or retried elsewhere: the Brief shows where it stands now.
          if (movedOn(e)) return true;
          fail(e, "Couldn't start writing the post again. Try again.");
          return false;
        },
      );
    },
    [act, fail],
  );

  return {
    load,
    reload,
    refresh,
    write,
    retry,
    busyIdea,
    failure: failedIdea
      ? ({ ideaId: failedIdea, error, notice, allowanceUsedUp } satisfies BriefFailure)
      : null,
  };
}
