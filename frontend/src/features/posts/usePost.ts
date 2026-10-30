import { useCallback, useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { postService, type Format, type PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { statusFrom } from './postStatus';
import { browserClock } from './text/clock';
import { TextController, type TextSnapshot } from './text/textController';
import { usePostCounts } from './usePostCounts';
import { useWritingFailure } from './useWritingFailure';

/** How long "Newer rewrites are in History" stays in the origin line. */
export const REWRITES_DROPPED_MS = 4_000;

export type PostLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; post: PostDetail; controller: TextController }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

function controllerFor(post: PostDetail): TextController {
  const { id } = post;
  return new TextController(post, {
    backend: {
      saveText: (parts) => postService.saveText(id, parts),
      restoreVersion: (versionNumber) => postService.restoreVersion(id, versionNumber),
      addVersion: (feedback, format, parts) => postService.addVersion(id, feedback, format, parts),
    },
    clock: browserClock,
    track,
  });
}

const noController = () => () => {};
const noSnapshot = () => null;

/**
 * One Post as the server has it. Its Text, Versions and the tools on them come from the Post's
 * `TextController`, as `text`. After an action that changes its Scheduled post, pass the answer
 * to `setScheduledPost` (null once deleted): the status follows, and so do the Post counts
 * behind the sidebar's Failed badge.
 */
export function usePost(postId: string) {
  const [load, setLoad] = useState<PostLoad>({ kind: 'loading' });
  const writing = useWritingFailure();
  const { fail, clear } = writing;
  const { refresh: refreshCounts } = usePostCounts();
  const { subscribed } = useSubscribed();
  const controller = load.kind === 'loaded' ? load.controller : null;
  const status = load.kind === 'loaded' ? load.post.status : null;

  const text: TextSnapshot | null = useSyncExternalStore(
    controller?.subscribe ?? noController,
    controller?.snapshot ?? noSnapshot,
  );

  const reload = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      const post = await postService.get(postId);
      setLoad({ kind: 'loaded', post, controller: controllerFor(post) });
    } catch (e) {
      if (errorStatus(e) === 404) setLoad({ kind: 'notFound' });
      else setLoad({ kind: 'failed', message: errorMessage(e, "Couldn't load the post.") });
    }
  }, [postId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => (controller ? () => controller.dispose() : undefined), [controller]);

  // Before paint, so the Text's tools never show a gate a step behind the page.
  useLayoutEffect(() => {
    if (controller && status) controller.setGate({ status, subscribed });
  }, [controller, status, subscribed]);

  const dropKey = text?.droppedRewrites?.key ?? null;
  const [dismissedDrop, setDismissedDrop] = useState<number | null>(null);
  useEffect(() => {
    if (dropKey === null) return;
    const timer = setTimeout(() => setDismissedDrop(dropKey), REWRITES_DROPPED_MS);
    return () => clearTimeout(timer);
  }, [dropKey]);

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
    setScheduledPost,
    controller,
    text,
    sendFeedback,
    rewritesDropped: dropKey !== null && dropKey !== dismissedDrop,
    error: writing.error,
    notice: writing.notice,
  };
}
