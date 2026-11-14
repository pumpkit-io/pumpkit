import { useCallback, useEffect, useRef, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { refusalMessage } from '@/features/posts/useWritingFailure';
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

export type BriefLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; brief: Brief }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

/** Why asking to write an Idea, or to retry its Post, failed. */
export interface BriefFailure {
  error: string | null;
  notice: string | null;
  allowanceUsedUp: AllowanceUsedUp | null;
}

const isWriting = (brief: Brief) =>
  briefPosts(brief).some(({ post }) => post.writingState === 'writing');

const withPostWriting = (brief: Brief, postId: string): Brief => ({
  ...brief,
  ideas: brief.ideas.map((idea) =>
    idea.post?.id === postId ? { ...idea, post: { ...idea.post, writingState: 'writing' } } : idea,
  ),
});

const stillUnwritten = (brief: Brief, postId: string) =>
  briefPosts(brief).some(({ post }) => post.id === postId && post.writingState === 'not_written');

/**
 * A Brief with its Ideas and Posts, read again while any Post is being written or a read after an
 * action failed. Reading stops when the page closes and on a 404 or 403; a failed read waits
 * longer before the next. `write` and `retry` start a Post's write; each Idea's request is
 * tracked apart in `busy`, and why one failed in `failures`, both by Idea id.
 */
export function useBrief(briefId: string) {
  const [load, setLoad] = useState<BriefLoad>({ kind: 'loading' });
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [failures, setFailures] = useState<Readonly<Record<string, BriefFailure>>>({});
  // A read after an action failed: the page keeps what it shows and reads again until one lands.
  const [stale, setStale] = useState(false);
  const { refresh: refreshSubscribed } = useSubscribed();
  // A read is numbered as it starts and an action's answer as it arrives, so a read that started
  // before an action answered can't replace that answer.
  const started = useRef(0);
  const shown = useRef(0);

  const loadFailed = useCallback((e: unknown) => {
    if (errorStatus(e) === 404) setLoad({ kind: 'notFound' });
    else setLoad({ kind: 'failed', message: "This brief couldn't be loaded." });
  }, []);

  const readBrief = useCallback(async () => {
    const number = ++started.current;
    return { number, brief: await briefService.get(briefId) };
  }, [briefId]);

  const show = useCallback(({ number, brief }: { number: number; brief: Brief }) => {
    if (number < shown.current) return;
    shown.current = number;
    setStale(false);
    setLoad({ kind: 'loaded', brief });
  }, []);

  const reload = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      show(await readBrief());
    } catch (e) {
      loadFailed(e);
    }
  }, [readBrief, show, loadFailed]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // The writes run on the server whether or not the page is open, so leaving only stops reading.
  const writing = load.kind === 'loaded' && isWriting(load.brief);
  useReadWhileWriting(writing || stale, readBrief, show, loadFailed);

  /** Reads the Brief in place; on failure the page stays as it is and reads again later. */
  const refresh = useCallback(async (): Promise<Brief | null> => {
    try {
      const read = await readBrief();
      show(read);
      return read.brief;
    } catch (e) {
      const status = errorStatus(e);
      if (status === 404 || status === 403) loadFailed(e);
      else setStale(true);
      return null;
    }
  }, [readBrief, show, loadFailed]);

  const fail = useCallback(
    (ideaId: string, e: unknown, fallback: string) => {
      // A refusal for want of a Subscription shows the prompt to subscribe, not an error.
      if (errorStatus(e) === 403) {
        refreshSubscribed();
        return;
      }
      const allowanceUsedUp = errorAllowanceUsedUp(e);
      if (allowanceUsedUp) track('allowance_used_up', { ran_out: allowanceUsedUp.ranOut });
      const failure = allowanceUsedUp
        ? { error: null, notice: null, allowanceUsedUp }
        : { ...refusalMessage(e, fallback), allowanceUsedUp: null };
      setFailures((all) => ({ ...all, [ideaId]: failure }));
    },
    [refreshSubscribed],
  );

  const act = useCallback(async (ideaId: string, request: () => Promise<void>) => {
    setFailures((all) => {
      const others = { ...all };
      delete others[ideaId];
      return others;
    });
    setBusy((ids) => new Set(ids).add(ideaId));
    try {
      await request();
    } finally {
      setBusy((ids) => {
        const left = new Set(ids);
        left.delete(ideaId);
        return left;
      });
    }
  }, []);

  /** Writes an Idea not written yet, from the Plan it already has. */
  const write = useCallback(
    (ideaId: string) => {
      track('post_version_requested', { kind: 'brief' });
      return act(ideaId, async () => {
        try {
          const brief = await briefService.write(briefId, [ideaId]);
          show({ number: ++started.current, brief });
        } catch (e) {
          // An earlier request wrote it and its answer was lost: the Brief now shows its Post.
          if (errorCode(e) === 'IDEAS_ALREADY_WRITTEN' && (await refresh())) return;
          fail(ideaId, e, "Couldn't start writing this post. Try again.");
        }
      });
    },
    [act, briefId, show, refresh, fail],
  );

  /** Writes a Post's first Version again, after Pumpkit couldn't write it. */
  const retry = useCallback(
    (ideaId: string, postId: string) => {
      track('post_version_requested', { kind: 'retry' });
      return act(ideaId, async () => {
        try {
          await postService.retry(postId);
          shown.current = ++started.current;
          setLoad((now) =>
            now.kind === 'loaded'
              ? { kind: 'loaded', brief: withPostWriting(now.brief, postId) }
              : now,
          );
        } catch (e) {
          // A 409 may mean it was written late or retried elsewhere; any other stands.
          if (errorStatus(e) === 409 && !errorAllowanceUsedUp(e)) {
            const brief = await refresh();
            if (brief && !stillUnwritten(brief, postId)) return;
          }
          fail(ideaId, e, "Couldn't start writing the post again. Try again.");
        }
      });
    },
    [act, refresh, fail],
  );

  return { load, reload, refresh, write, retry, busy, failures };
}
