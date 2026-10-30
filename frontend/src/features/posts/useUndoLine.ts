import { useCallback, useEffect, useRef, useState } from 'react';
import { track } from '@/lib/analytics';
import type { PostDetail } from '@/services/postService';
import { TextHistory, type CommitKind, type EditCause, type TextStep } from './textHistory';

/** How long "Newer rewrites are in History" stays in the origin line. */
export const REWRITES_DROPPED_MS = 4_000;

/** One change to highlight: the Parts before it and after it, `key` telling changes apart. */
export interface TextTrace {
  key: number;
  before: string[];
  after: string[];
}

/** What a screen reader hears after a step, `key` making a repeated message heard again. */
export interface UndoAnnouncement {
  key: number;
  message: string;
}

export type UndoDirection = 'undo' | 'redo';

/** A move along the undo line, from one step to the one the Text should now show. */
export interface UndoMove {
  from: TextStep;
  to: TextStep;
}

function stepName(step: TextStep): string {
  if (step.kind === 'rewrite') return 'rewrite from Feedback';
  if (step.kind === 'restore') return `restore of Version ${step.origin.versionNumber}`;
  return 'your edit';
}

function historyOf(post: PostDetail): TextHistory | null {
  const { text } = post;
  if (!text) return null;
  const parts = text.parts.map((p) => p.text);
  const version = post.versions.find((v) => v.number === text.versionNumber);
  return new TextHistory(
    {
      parts,
      versionNumber: text.versionNumber,
      versionParts: version?.parts.map((p) => p.text) ?? parts,
    },
    { now: () => Date.now() },
  );
}

/**
 * The undo line of one Post's Text in this tab, with what the page shows around it: the change
 * to highlight, what to announce, and the notice when an edit drops rewrites from redo. It moves
 * along the line; putting the Text there, and saving it, is the caller's.
 */
export function useUndoLine() {
  const history = useRef<TextHistory | null>(null);
  const [ends, setEnds] = useState({ canUndo: false, canRedo: false });
  const [trace, setTrace] = useState<TextTrace | null>(null);
  const [announcement, setAnnouncement] = useState<UndoAnnouncement | null>(null);
  const [droppedNotice, setDroppedNotice] = useState<number | null>(null);
  const keys = useRef(0);

  useEffect(() => {
    if (droppedNotice === null) return;
    const timer = setTimeout(() => setDroppedNotice(null), REWRITES_DROPPED_MS);
    return () => clearTimeout(timer);
  }, [droppedNotice]);

  const sync = useCallback(() => {
    const h = history.current;
    setEnds({ canUndo: !!h?.canUndo, canRedo: !!h?.canRedo });
  }, []);

  const announce = useCallback((message: string) => {
    keys.current += 1;
    setAnnouncement({ key: keys.current, message });
  }, []);

  const highlight = useCallback((before: string[], after: string[]) => {
    keys.current += 1;
    setTrace({ key: keys.current, before, after });
  }, []);

  const report = useCallback((droppedRewrites: number) => {
    if (droppedRewrites === 0) return;
    track('redo_rewrites_dropped', { count: droppedRewrites });
    keys.current += 1;
    setDroppedNotice(keys.current);
  }, []);

  /** Starts an empty line at the Post's Text as loaded. */
  const start = useCallback(
    (post: PostDetail) => {
      history.current = historyOf(post);
      setTrace(null);
      setDroppedNotice(null);
      sync();
    },
    [sync],
  );

  const edit = useCallback(
    (parts: string[], cause: EditCause) => {
      const h = history.current;
      if (!h) return;
      report(h.edit(parts, cause).droppedRewrites);
      setTrace(null);
      sync();
    },
    [report, sync],
  );

  const commit = useCallback(
    (parts: string[], kind: CommitKind, versionNumber: number) => {
      const h = history.current;
      if (!h) return;
      const before = h.current.parts;
      report(h.commit(parts, kind, versionNumber).droppedRewrites);
      highlight(before, parts);
      if (kind === 'restore') announce(`Restored Version ${versionNumber}`);
      sync();
    },
    [report, highlight, announce, sync],
  );

  const move = useCallback(
    (direction: UndoDirection): UndoMove | null => {
      const h = history.current;
      if (!h) return null;
      const from = h.current;
      const moved = direction === 'undo' ? h.undo() : h.redo();
      if (!moved) return null;
      highlight(from.parts, moved.current.parts);
      announce(`${direction === 'undo' ? 'Undid' : 'Redid'}: ${stepName(moved.step)}`);
      track(direction === 'undo' ? 'text_undone' : 'text_redone', { step: moved.step.kind });
      sync();
      return { from, to: moved.current };
    },
    [highlight, announce, sync],
  );

  /** Takes back a move the server refused, so the line matches the Text again. */
  const takeBack = useCallback(
    (direction: UndoDirection) => {
      const h = history.current;
      if (!h) return;
      if (direction === 'undo') h.redo();
      else h.undo();
      setTrace(null);
      sync();
    },
    [sync],
  );

  /** The Parts where the line is now, typing included. */
  const currentParts = useCallback(() => history.current?.current.parts ?? null, []);

  return {
    ...ends,
    trace,
    announcement,
    rewritesDropped: droppedNotice !== null,
    start,
    edit,
    commit,
    move,
    takeBack,
    currentParts,
  };
}
