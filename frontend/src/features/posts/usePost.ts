import { useCallback, useEffect, useRef, useState } from 'react';
import { track } from '@/lib/analytics';
import { xWeightedLength } from '@/lib/xLength';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { postService, textOf, type Format, type PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { statusFrom } from './postStatus';
import type { EditCause } from './textHistory';
import { usePostCounts } from './usePostCounts';
import { useTextAutosave } from './useTextAutosave';
import { useUndoLine, type UndoDirection } from './useUndoLine';
import { isRefusal, useWritingFailure } from './useWritingFailure';

export type PostLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; post: PostDetail }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

const textsOf = (parts: { text: string }[]) => parts.map((p) => p.text);

/**
 * The Post with its Text's Parts replaced by `texts`, counted as X counts them, and edited while
 * they differ from the Version the Text came from, as the server decides it. `versionNumber`
 * moves the Text to another Version, for undo and redo across a rewrite or a restore.
 */
function withEditedText(
  post: PostDetail,
  texts: string[],
  versionNumber = post.text?.versionNumber,
): PostDetail {
  const { text } = post;
  if (!text) return post;
  const source = post.versions.find((v) => v.number === versionNumber);
  return {
    ...post,
    text: {
      ...text,
      format: source?.format ?? text.format,
      versionNumber: source?.number ?? text.versionNumber,
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
 * One Post as the server has it, with its Text edited in place and saved on its own, Feedback
 * on it, and undo and redo along every change to it in this tab. After an action that changes its
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
  const { edit: saveSoon, flush: flushEdits, discard: discardEdits } = autosave;
  const line = useUndoLine();
  const { start: startLine, edit: recordEdit, commit, move, takeBack, currentParts } = line;
  // Restores for undo and redo go out one at a time, so the server ends on the last one.
  const restoring = useRef<Promise<void>>(Promise.resolve());
  const restoresOut = useRef(0);

  /** Saves the Text on screen now, an undo's restore included; true once the server has it. */
  const flushText = useCallback(
    (): Promise<boolean> =>
      restoresOut.current > 0 ? restoring.current.then(flushEdits) : flushEdits(),
    [flushEdits],
  );

  const reload = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      const post = await postService.get(postId);
      startLine(post);
      setLoad({ kind: 'loaded', post });
    } catch (e) {
      if (errorStatus(e) === 404) setLoad({ kind: 'notFound' });
      else setLoad({ kind: 'failed', message: errorMessage(e, "Couldn't load the Post.") });
    }
  }, [postId, startLine]);

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
        commit(textsOf(version.parts), 'rewrite', version.number);
        return true;
      } catch (e) {
        if (!isRefusal(e)) track('post_version_failed', { kind: 'feedback' });
        fail(e, "Couldn't write the next Version. Try again.");
        return false;
      } finally {
        setIsWriting(false);
      }
    },
    [postId, clear, fail, update, flushText, commit],
  );

  const showText = useCallback(
    (texts: string[], versionNumber?: number) =>
      update((post) => (post.id === postId ? withEditedText(post, texts, versionNumber) : post)),
    [postId, update],
  );

  /** Replaces every Part of the Text with the User's, shown at once and saved after a pause. */
  const editText = useCallback(
    (texts: string[], cause: EditCause) => {
      recordEdit(texts, cause);
      showText(texts);
      saveSoon(texts);
    },
    [recordEdit, showText, saveSoon],
  );

  /**
   * Steps the Text back or forward along the undo line. Within one Version it saves the Parts;
   * across a rewrite or a restore it restores that Version first, since a save keeps the Text's
   * Version and shape, then saves the Parts if they were edited.
   */
  const stepText = useCallback(
    (direction: UndoDirection) => {
      const moved = move(direction);
      if (!moved) return;
      const { from, to } = moved;
      setRestoreError(null);
      showText(to.parts, to.origin.versionNumber);
      if (to.origin.versionNumber === from.origin.versionNumber) {
        saveSoon(to.parts);
        return;
      }
      restoresOut.current += 1;
      restoring.current = restoring.current.then(async () => {
        await discardEdits();
        try {
          const text = await postService.restoreVersion(postId, to.origin.versionNumber);
          track('version_restored', { source: 'undo' });
          // The User may have typed while the restore was out.
          const parts = currentParts() ?? to.parts;
          update((post) => (post.id === postId ? withEditedText({ ...post, text }, parts) : post));
          if (parts.some((t, i) => t !== text.parts[i]?.text)) saveSoon(parts);
        } catch (e) {
          takeBack(direction);
          showText(from.parts, from.origin.versionNumber);
          setRestoreError(errorMessage(e, `Couldn't ${direction} that change. Try again.`));
        } finally {
          restoresOut.current -= 1;
        }
      });
    },
    [postId, move, takeBack, currentParts, showText, update, saveSoon, discardEdits],
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
        commit(textsOf(text.parts), 'restore', versionNumber);
        track('version_restored', { source: 'history' });
      } catch (e) {
        setRestoreError(errorMessage(e, `Couldn't restore Version ${versionNumber}. Try again.`));
      }
    },
    [postId, update, discardEdits, commit],
  );

  return {
    load,
    reload,
    setScheduledPost,
    addFeedback,
    restoreVersion,
    restoreError,
    editText,
    undo: line.canUndo ? () => stepText('undo') : undefined,
    redo: line.canRedo ? () => stepText('redo') : undefined,
    trace: line.trace,
    announcement: line.announcement,
    rewritesDropped: line.rewritesDropped,
    textSave: autosave.state,
    flushText,
    isWriting,
    error: writing.error,
    notice: writing.notice,
  };
}
