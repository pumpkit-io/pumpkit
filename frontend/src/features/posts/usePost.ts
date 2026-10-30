import { useCallback, useEffect, useRef, useState } from 'react';
import { track } from '@/lib/analytics';
import { xWeightedLength } from '@/lib/xLength';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { postService, textOf, type Format, type PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { statusFrom } from './postStatus';
import { usePostCounts } from './usePostCounts';
import { useTextAutosave } from './useTextAutosave';
import { isRefusal, useWritingFailure } from './useWritingFailure';

export type PostLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; post: PostDetail }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

/**
 * The Post with its Text's Parts replaced by `texts`, counted as X counts them, and edited while
 * they differ from the Version the Text came from, as the server decides it.
 */
function withEditedText(post: PostDetail, texts: string[]): PostDetail {
  const { text } = post;
  if (!text) return post;
  const source = post.versions.find((v) => v.number === text.versionNumber);
  return {
    ...post,
    text: {
      ...text,
      parts: texts.map((t, i) => ({
        text: t,
        charCount: xWeightedLength(t),
        charLimit: text.parts[i]?.charLimit ?? text.parts[0]?.charLimit ?? 280,
      })),
      edited:
        !source ||
        source.parts.length !== texts.length ||
        source.parts.some((p, i) => p.text !== texts[i]),
    },
  };
}

/**
 * One Post as the server has it, with its Text edited in place and saved on its own, and Feedback
 * on it. After an action that changes its
 * Scheduled post, pass the answer to `setScheduledPost` (null once deleted): the status follows,
 * and so do the Post counts behind the sidebar's Failed badge.
 */
export function usePost(postId: string) {
  const [load, setLoad] = useState<PostLoad>({ kind: 'loading' });
  const [isWriting, setIsWriting] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const writing = useWritingFailure();
  const { fail, clear } = writing;
  const { refresh: refreshCounts } = usePostCounts();
  const autosave = useTextAutosave(postId);
  const { edit: saveSoon, flush: flushText, discard: discardEdits } = autosave;

  const reload = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      setLoad({ kind: 'loaded', post: await postService.get(postId) });
    } catch (e) {
      if (errorStatus(e) === 404) setLoad({ kind: 'notFound' });
      else setLoad({ kind: 'failed', message: errorMessage(e, "Couldn't load the Post.") });
    }
  }, [postId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // What Feedback is given on: the Text on screen, which the server checks it has saved.
  const shownText = useRef<string[]>([]);
  useEffect(() => {
    if (load.kind === 'loaded')
      shownText.current = (load.post.text?.parts ?? []).map((p) => p.text);
  }, [load]);

  const update = useCallback((change: (post: PostDetail) => PostDetail) => {
    setLoad((current) =>
      current.kind === 'loaded' ? { kind: 'loaded', post: change(current.post) } : current,
    );
  }, []);

  const setScheduledPost = useCallback(
    (scheduledPost: ScheduledPost | null) => {
      update((post) => ({
        ...post,
        scheduledPost,
        status: statusFrom(scheduledPost?.state ?? null),
      }));
      refreshCounts();
    },
    [update, refreshCounts],
  );

  /** Resolves true once the new Version is the Post's Text, so the caller can clear its box. */
  const addFeedback = useCallback(
    async (feedback: string, format: Format): Promise<boolean> => {
      setIsWriting(true);
      clear();
      setRestoreError(null);
      // Feedback rewrites the Text the server has, so it must have the User's last edit.
      if (!(await flushText())) {
        setIsWriting(false);
        return false;
      }
      track('post_version_requested', { kind: 'feedback' });
      try {
        const version = await postService.addVersion(postId, feedback, format, shownText.current);
        update((post) =>
          post.id === postId
            ? { ...post, versions: [...post.versions, version], text: textOf(version) }
            : post,
        );
        return true;
      } catch (e) {
        if (!isRefusal(e)) track('post_version_failed', { kind: 'feedback' });
        fail(e, "Couldn't write the next Version. Try again.");
        return false;
      } finally {
        setIsWriting(false);
      }
    },
    [postId, clear, fail, update, flushText],
  );

  /**
   * Replaces every Part of the Text with the User's, shown at once and saved after a pause.
   * Undo and redo (#197) go through here too.
   */
  const editText = useCallback(
    (texts: string[]) => {
      update((post) => (post.id === postId ? withEditedText(post, texts) : post));
      saveSoon(texts);
    },
    [postId, update, saveSoon],
  );

  /** Makes a Version from History the Post's Text; a refusal leaves the Text and says why. */
  const restoreVersion = useCallback(
    async (versionNumber: number) => {
      setRestoreError(null);
      // The restored Version replaces any edit, and a late save mustn't overwrite it.
      await discardEdits();
      try {
        const text = await postService.restoreVersion(postId, versionNumber);
        update((post) => (post.id === postId ? { ...post, text } : post));
        track('version_restored', { source: 'history' });
      } catch (e) {
        setRestoreError(errorMessage(e, `Couldn't restore Version ${versionNumber}. Try again.`));
      }
    },
    [postId, update, discardEdits],
  );

  return {
    load,
    reload,
    setScheduledPost,
    addFeedback,
    restoreVersion,
    restoreError,
    editText,
    textSave: autosave.state,
    flushText,
    isWriting,
    error: writing.error,
    notice: writing.notice,
  };
}
