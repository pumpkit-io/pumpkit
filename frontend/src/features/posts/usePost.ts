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
  VersionNotWritten,
  type FailedFeedback,
  type Format,
  type PostDetail,
  type UnwrittenPost,
} from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { statusFrom } from './postStatus';
import { browserClock } from './text/clock';
import { TextController, type DroppedRewrites, type TextSnapshot } from './text/textController';
import { usePostCounts } from './usePostCounts';
import { useReadWhileWriting } from './useReadWhileWriting';
import { useWritingFailure } from './useWritingFailure';

/** How long "Newer rewrites are in History" stays in the origin line. */
export const REWRITES_DROPPED_MS = 4_000;

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
      addVersion: (feedback, format, parts, signal) =>
        postService.addVersion(id, feedback, format, parts, signal),
      awaitVersion: (after, signal) => postService.awaitVersion(id, after, signal),
    },
    clock: browserClock,
    track,
  });
}

const FEEDBACK_FAILED = "Couldn't write the next version. Try again.";

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
  // Feedback whose Version Pumpkit couldn't write, offered again until the User moves on.
  const [failedFeedback, setFailedFeedback] = useState<FailedFeedback | null>(null);

  /** Shows why Feedback wrote no Version, keeping the Feedback the server says failed. */
  const feedbackFailed = useCallback(
    (e: unknown) => {
      if (e instanceof VersionNotWritten && e.failedFeedback) setFailedFeedback(e.failedFeedback);
      fail(e, FEEDBACK_FAILED);
    },
    [fail],
  );
  const { refresh: refreshCounts } = usePostCounts();
  const controller = load.kind === 'loaded' ? load.controller : null;
  const status = load.kind === 'loaded' ? load.post.status : null;

  const text: TextSnapshot | null = useSyncExternalStore(
    controller?.subscribe ?? noSubscribe,
    controller?.snapshot ?? noSnapshot,
  );

  const show = useCallback(
    (post: PostDetail | UnwrittenPost) => {
      if (isUnwritten(post)) setLoad({ kind: 'unwritten', post });
      else {
        setLoad({ kind: 'loaded', post, controller: controllerFor(post) });
        if (post.failedFeedback && !post.writing)
          feedbackFailed(new VersionNotWritten(post.failedFeedback));
      }
    },
    [feedbackFailed],
  );

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
  const readPost = useCallback(() => postService.get(postId), [postId]);
  const readWhileWriting = useCallback(
    (post: PostDetail | UnwrittenPost) => {
      if (isUnwritten(post) && post.writingState === 'writing') return;
      if (isUnwritten(post))
        track('post_version_failed', { kind: retried.current ? 'retry' : 'brief' });
      show(post);
    },
    [show],
  );
  useReadWhileWriting(writingPost, readPost, readWhileWriting, loadFailed);

  const [retrying, setRetrying] = useState(false);
  const unwritten = load.kind === 'unwritten' ? load.post : null;
  /** Writes the first Version again, after Pumpkit couldn't write it. */
  const retry = useCallback(async () => {
    clear();
    setRetrying(true);
    track('post_version_requested', { kind: 'retry' });
    try {
      const started = await postService.retry(postId);
      // Starting a write answers without the Post's place in its Brief, so it keeps the one it had.
      show(
        unwritten
          ? { ...started, briefId: unwritten.briefId, placeInBrief: unwritten.placeInBrief }
          : await postService.get(postId),
      );
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
  }, [postId, unwritten, show, clear, fail]);

  useEffect(() => (controller ? () => controller.dispose() : undefined), [controller]);

  // A Post read while Feedback's Version is being written shows the writing state until it lands.
  const rewriting = load.kind === 'loaded' && load.post.writing ? load.controller : null;
  useEffect(() => {
    if (!rewriting) return;
    let live = true;
    void rewriting.resumeWriting().then((outcome) => {
      if (live && typeof outcome === 'object') feedbackFailed(outcome.failed);
    });
    return () => {
      live = false;
      rewriting.stopWaiting();
    };
  }, [rewriting, feedbackFailed]);

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
      setFailedFeedback(null);
      const outcome = await controller.sendFeedback(feedback, format);
      if (typeof outcome === 'object') feedbackFailed(outcome.failed);
      return outcome === 'sent';
    },
    [controller, clear, feedbackFailed],
  );

  const dismissFailedFeedback = useCallback(() => {
    clear();
    setFailedFeedback(null);
    // Not awaited: should it fail, the Post shows the failure again when next opened, nothing worse.
    postService.dismissFailedFeedback(postId).catch(() => {});
  }, [postId, clear]);

  return {
    load,
    reload,
    retry,
    retrying,
    setScheduledPost,
    gone,
    text,
    sendFeedback,
    failedFeedback,
    dismissFailedFeedback,
    rewritesDropped: dropped !== null && dropped !== dismissedDrop,
    error: writing.error,
    notice: writing.notice,
    allowanceUsedUp: writing.allowanceUsedUp,
  };
}
