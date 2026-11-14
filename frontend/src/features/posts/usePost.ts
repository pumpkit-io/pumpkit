import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';
import { track } from '@/lib/analytics';
import { errorAllowanceUsedUp, errorMessage, errorStatus } from '@/services/apiErrors';
import {
  isUnwritten,
  postService,
  type Format,
  type PostDetail,
  type UnwrittenPost,
} from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { statusFrom } from './postStatus';
import { browserClock } from './text/clock';
import { TextController, type DroppedRewrites, type TextSnapshot } from './text/textController';
import { usePostCounts } from './usePostCounts';
import { useWritingFailure } from './useWritingFailure';

/** How long "Newer rewrites are in History" stays in the origin line. */
export const REWRITES_DROPPED_MS = 4_000;
/** How often the page reads a Post again while its first Version is being written. */
export const WRITING_POLL_MS = 3_000;
/** The longest wait between reads, which doubles after each read that fails. */
export const WRITING_POLL_MAX_MS = 60_000;

export type PostLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; post: PostDetail; controller: TextController }
  | { kind: 'unwritten'; post: UnwrittenPost }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

function controllerFor(post: PostDetail): TextController {
  const { id } = post;
  return new TextController(post, {
    backend: {
      saveText: (parts, firstReply) => postService.saveText(id, parts, firstReply),
      restoreVersion: (versionNumber) => postService.restoreVersion(id, versionNumber),
      addVersion: (feedback, format, parts) => postService.addVersion(id, feedback, format, parts),
    },
    clock: browserClock,
    track,
  });
}

const noSubscribe = () => () => {};
const noSnapshot = () => null;

/**
 * One Post as the server has it, its Text and Versions as `text` from its `TextController`. Pass
 * `setScheduledPost` each new Scheduled post (null once deleted): status and Post counts follow.
 */
export function usePost(postId: string) {
  const [load, setLoad] = useState<PostLoad>({ kind: 'loading' });
  const writing = useWritingFailure();
  const { fail, clear } = writing;
  const { refresh: refreshCounts } = usePostCounts();
  const controller = load.kind === 'loaded' ? load.controller : null;
  const status = load.kind === 'loaded' ? load.post.status : null;

  const text: TextSnapshot | null = useSyncExternalStore(
    controller?.subscribe ?? noSubscribe,
    controller?.snapshot ?? noSnapshot,
  );

  const show = useCallback((post: PostDetail | UnwrittenPost) => {
    if (isUnwritten(post)) setLoad({ kind: 'unwritten', post });
    else setLoad({ kind: 'loaded', post, controller: controllerFor(post) });
  }, []);

  /** Shows why the Post couldn't be read, in place of the Post. */
  const loadFailed = useCallback((e: unknown) => {
    if (errorStatus(e) === 404) setLoad({ kind: 'notFound' });
    else setLoad({ kind: 'failed', message: errorMessage(e, "Couldn't load the post.") });
  }, []);

  const reload = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      show(await postService.get(postId));
    } catch (e) {
      loadFailed(e);
    }
  }, [postId, show, loadFailed]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Whether the write being read is one this page retried, for `post_version_failed`.
  const retried = useRef(false);

  // The write runs on the server whether or not the page is open, so leaving only stops reading.
  const writingPost = load.kind === 'unwritten' && load.post.writingState === 'writing';
  const [poll, setPoll] = useState({ count: 0, failures: 0 });
  useEffect(() => {
    if (!writingPost) return;
    let stopped = false;
    const delay = Math.min(WRITING_POLL_MS * 2 ** poll.failures, WRITING_POLL_MAX_MS);
    const timer = setTimeout(() => {
      postService.get(postId).then(
        (post) => {
          if (stopped) return;
          setPoll(({ count }) => ({ count: count + 1, failures: 0 }));
          if (isUnwritten(post) && post.writingState === 'writing') return;
          if (isUnwritten(post))
            track('post_version_failed', { kind: retried.current ? 'retry' : 'brief' });
          show(post);
        },
        (e: unknown) => {
          if (stopped) return;
          const status = errorStatus(e);
          if (status === 404 || status === 403) loadFailed(e);
          else setPoll(({ count, failures }) => ({ count: count + 1, failures: failures + 1 }));
        },
      );
    }, delay);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [writingPost, poll, postId, show, loadFailed]);

  const [retrying, setRetrying] = useState(false);
  /** Writes the first Version again, after Pumpkit couldn't write it. */
  const retry = useCallback(async () => {
    clear();
    setRetrying(true);
    track('post_version_requested', { kind: 'retry' });
    try {
      show(await postService.retry(postId));
      retried.current = true;
    } catch (e) {
      // A 409 other than the allowance's may mean the Post moved on: written late, or retried elsewhere.
      const current =
        errorStatus(e) === 409 && !errorAllowanceUsedUp(e)
          ? await postService.get(postId).catch(() => null)
          : null;
      if (current && !(isUnwritten(current) && current.writingState === 'not_written'))
        show(current);
      else fail(e, "Couldn't start writing the post again. Try again.");
    } finally {
      setRetrying(false);
    }
  }, [postId, show, clear, fail]);

  useEffect(() => (controller ? () => controller.dispose() : undefined), [controller]);

  // Before paint, so the Text's tools never show a gate a step behind the page.
  useLayoutEffect(() => {
    if (controller && status) controller.setGate({ status });
  }, [controller, status]);

  // Compared by identity: each controller counts its keys from 1, so a key repeats across Posts.
  const dropped = text?.droppedRewrites ?? null;
  const [dismissedDrop, setDismissedDrop] = useState<DroppedRewrites | null>(null);
  useEffect(() => {
    if (!dropped) return;
    const timer = setTimeout(() => setDismissedDrop(dropped), REWRITES_DROPPED_MS);
    return () => clearTimeout(timer);
  }, [dropped]);

  const setScheduledPost = useCallback(
    (scheduledPost: ScheduledPost | null) => {
      setLoad((current) =>
        current.kind === 'loaded' && current.post.id === postId
          ? {
              ...current,
              post: {
                ...current.post,
                scheduledPost,
                status: statusFrom(scheduledPost?.state ?? null),
              },
            }
          : current,
      );
      refreshCounts();
    },
    [postId, refreshCounts],
  );

  /** The Post was deleted while the page was open. */
  const gone = useCallback(() => {
    setLoad({ kind: 'notFound' });
    refreshCounts();
  }, [refreshCounts]);

  /** Resolves true once the new Version is the Post's Text, so the caller can clear its box. */
  const sendFeedback = useCallback(
    async (feedback: string, format: Format): Promise<boolean> => {
      if (!controller) return false;
      clear();
      const outcome = await controller.sendFeedback(feedback, format);
      if (typeof outcome === 'object')
        fail(outcome.failed, "Couldn't write the next version. Try again.");
      return outcome === 'sent';
    },
    [controller, clear, fail],
  );

  return {
    load,
    reload,
    retry,
    retrying,
    setScheduledPost,
    gone,
    text,
    sendFeedback,
    rewritesDropped: dropped !== null && dropped !== dismissedDrop,
    error: writing.error,
    notice: writing.notice,
    allowanceUsedUp: writing.allowanceUsedUp,
  };
}
