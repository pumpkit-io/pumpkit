import type { track as trackEvent } from '@/lib/analytics';
import { X_POST_MAX_CHARS, xWeightedLength } from '@/lib/xLength';
import { errorMessage } from '@/services/apiErrors';
import {
  formatOf,
  textOf,
  type Format,
  type PostDetail,
  type PostStatus,
  type PostText,
  type Version,
} from '@/services/postService';
import {
  sameParts,
  TextHistory,
  type CommitKind,
  type EditCause,
  type TextStep,
} from '../textHistory';
import { isRefusal } from '../useWritingFailure';
import type { Clock } from './clock';
import { TextSaver, type TextSaveState } from './textSaver';

export type { TextSaveState };

/** The server calls the Text needs, for one Post: `postService` in production. */
export interface TextBackend {
  saveText: (parts: string[]) => Promise<PostText>;
  restoreVersion: (versionNumber: number) => Promise<PostText>;
  addVersion: (feedback: string, format: Format, parts: string[]) => Promise<Version>;
}

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

/** Rewrites an edit just dropped from redo, which History still holds. */
export interface DroppedRewrites {
  key: number;
  count: number;
}

/** What the User may do to the Text now; every method ignores a call this forbids. */
export interface TextAbilities {
  edit: boolean;
  undo: boolean;
  redo: boolean;
  restore: boolean;
  sendFeedback: boolean;
  postTo: boolean;
}

export interface TextSnapshot {
  text: PostText | null;
  versions: Version[];
  /** The Text as the Version it came from, for what reads a Version's shape; else the latest. */
  textVersion: Version | undefined;
  can: TextAbilities;
  writing: boolean;
  restoring: boolean;
  save: TextSaveState;
  /** Why the last restore, undo or redo didn't reach the server. */
  restoreError: string | null;
  trace: TextTrace | null;
  announcement: UndoAnnouncement | null;
  droppedRewrites: DroppedRewrites | null;
}

/** What the Text's tools hang on that the controller doesn't own. */
export interface TextGate {
  status: PostStatus;
  /** Null until the Subscription has loaded. */
  subscribed: boolean | null;
}

/** 'notSaved' when the last edit didn't reach the server, or nothing was sent at all. */
export type FeedbackOutcome = 'sent' | 'notSaved' | { failed: unknown };

type Direction = 'undo' | 'redo';

const textsOf = (parts: { text: string }[]) => parts.map((p) => p.text);

function stepName(step: TextStep): string {
  if (step.kind === 'rewrite') return 'rewrite from feedback';
  if (step.kind === 'restore') return `restore of version ${step.origin.versionNumber}`;
  return 'your edit';
}

/**
 * One loaded Post's Text and Versions in this tab: edits, autosave, undo, redo, restores, Feedback.
 * One restore is out at a time, and no undo, redo or restore starts before it lands.
 */
export class TextController {
  private text: PostText | null;
  private versions: Version[];
  private readonly history: TextHistory | null;
  private readonly saver: TextSaver;
  private gate: TextGate;
  private writing = false;
  private restoring: Promise<void> | null = null;
  private save: TextSaveState = { kind: 'saved' };
  private restoreError: string | null = null;
  private trace: TextTrace | null = null;
  private announcement: UndoAnnouncement | null = null;
  private droppedRewrites: DroppedRewrites | null = null;
  private keys = 0;
  private listeners = new Set<() => void>();
  private current: TextSnapshot;

  constructor(
    post: PostDetail,
    private readonly deps: { backend: TextBackend; clock: Clock; track: typeof trackEvent },
  ) {
    this.text = post.text;
    this.versions = post.versions;
    this.gate = { status: post.status, subscribed: null };
    this.history = this.historyOf(post);
    this.saver = new TextSaver(
      (parts) => this.saveOnServer(parts),
      (state) => {
        this.save = state;
        this.emit();
      },
      (parts) =>
        deps.track('post_text_edited', { format: formatOf(parts), part_count: parts.length }),
      deps.clock,
    );
    this.current = this.build();
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  snapshot = (): TextSnapshot => this.current;

  setGate(gate: TextGate) {
    if (gate.status === this.gate.status && gate.subscribed === this.gate.subscribed) return;
    this.gate = gate;
    this.emit();
  }

  /** Replaces every Part of the Text with the User's, shown at once and saved after a pause. */
  edit(parts: string[], cause: EditCause) {
    if (!this.current.can.edit || !this.history) return;
    this.report(this.history.edit(parts, cause).droppedRewrites);
    this.trace = null;
    this.show(parts);
    // A restore out saves the Text it lands on itself.
    if (!this.restoring) this.saver.edit(parts);
    this.emit();
  }

  undo() {
    if (this.current.can.undo) this.step('undo');
  }

  redo() {
    if (this.current.can.redo) this.step('redo');
  }

  /** Makes a Version from History the Post's Text; a refusal leaves the Text and says why. */
  restore(versionNumber: number) {
    if (!this.current.can.restore) return;
    this.restoreError = null;
    this.restoreOnServer(
      versionNumber,
      (text) => {
        this.text = text;
        this.commit(textsOf(text.parts), 'restore', versionNumber);
        this.deps.track('version_restored', { source: 'history' });
      },
      (e) => {
        this.restoreError = errorMessage(
          e,
          `Couldn't restore version ${versionNumber}. Try again.`,
        );
      },
    );
  }

  /** Resolves true once the server has the Text on screen, a restore out included. */
  settle(): Promise<boolean> {
    return this.restoring ? this.restoring.then(() => this.saver.flush()) : this.saver.flush();
  }

  /** Rewrites the Text on screen from Feedback, once the server has it. */
  async sendFeedback(feedback: string, format: Format): Promise<FeedbackOutcome> {
    if (!this.current.can.sendFeedback) return 'notSaved';
    this.writing = true;
    this.restoreError = null;
    this.emit();
    try {
      // Feedback rewrites the Text the server has, so it must have the User's last edit.
      if (!(await this.settle())) return 'notSaved';
      this.deps.track('post_version_requested', { kind: 'feedback' });
      const parts = textsOf(this.text?.parts ?? []);
      try {
        const version = await this.deps.backend.addVersion(feedback, format, parts);
        this.versions = [...this.versions, version];
        this.text = textOf(version);
        this.commit(textsOf(version.parts), 'rewrite', version.number);
        return 'sent';
      } catch (e) {
        if (!isRefusal(e)) this.deps.track('post_version_failed', { kind: 'feedback' });
        return { failed: e };
      }
    } finally {
      this.writing = false;
      this.emit();
    }
  }

  /** Sends any edit the pause still holds, as the page goes away. */
  dispose() {
    this.saver.dispose();
  }

  private historyOf(post: PostDetail): TextHistory | null {
    const { text } = post;
    if (!text) return null;
    const parts = textsOf(text.parts);
    const version = post.versions.find((v) => v.number === text.versionNumber);
    return new TextHistory(
      {
        parts,
        versionNumber: text.versionNumber,
        versionParts: version ? textsOf(version.parts) : parts,
      },
      this.deps.clock,
    );
  }

  /**
   * Steps the Text along the undo line. Within one Version it saves the Parts; across a rewrite
   * or a restore it restores that Version first, since a save keeps the Text's Version and shape.
   */
  private step(direction: Direction) {
    const history = this.history!;
    const before = history.mark();
    const from = history.current;
    const moved = direction === 'undo' ? history.undo() : history.redo();
    if (!moved) return;
    const to = moved.current;
    this.highlight(from.parts, to.parts);
    this.announce(`${direction === 'undo' ? 'Undid' : 'Redid'}: ${stepName(moved.step)}`);
    this.deps.track(direction === 'undo' ? 'text_undone' : 'text_redone', {
      step: moved.step.kind,
    });
    this.restoreError = null;
    this.show(to.parts, to.origin.versionNumber);
    if (to.origin.versionNumber === from.origin.versionNumber) {
      this.saver.edit(to.parts);
      this.emit();
      return;
    }
    this.restoreOnServer(
      to.origin.versionNumber,
      (text) => {
        this.deps.track('version_restored', { source: 'undo' });
        // The User may have typed while the restore was out.
        this.text = text;
        this.show(history.current.parts);
      },
      (e) => {
        history.rewind(before);
        this.trace = null;
        // Any rewrites an edit dropped since are back on the line.
        this.droppedRewrites = null;
        this.show(from.parts, from.origin.versionNumber);
        this.restoreError = errorMessage(e, `Couldn't ${direction} that change. Try again.`);
      },
    );
  }

  /** Restores a Version on the server, then saves any typing done while it was out. */
  private restoreOnServer(
    versionNumber: number,
    landed: (text: PostText) => void,
    refused: (e: unknown) => void,
  ) {
    this.restoring = (async () => {
      // The restore replaces any edit, and a late save mustn't overwrite it.
      await this.saver.discard();
      try {
        landed(await this.deps.backend.restoreVersion(versionNumber));
      } catch (e) {
        refused(e);
      }
      this.restoring = null;
      const step = this.history?.current;
      if (step?.origin.edited) this.saver.edit(step.parts);
      this.emit();
    })();
    this.emit();
  }

  /**
   * Takes the server's answer to a save, unless the Text moved on or a restore is out; a restore
   * waits for the save out before it starts, so its answer always lands while the restore is out.
   */
  private async saveOnServer(parts: string[]): Promise<void> {
    const text = await this.deps.backend.saveText(parts);
    const onScreen = textsOf(this.text?.parts ?? []);
    if (this.restoring || !sameParts(parts, onScreen)) return;
    this.text = text;
    this.emit();
  }

  /**
   * Puts `parts` on screen, counted as X counts them, and edited while they differ from the
   * Version, as the server decides it. `versionNumber` moves the Text to another Version.
   */
  private show(parts: string[], versionNumber = this.text?.versionNumber) {
    const { text } = this;
    if (!text) return;
    const source = this.versions.find((v) => v.number === versionNumber);
    this.text = {
      ...text,
      format: source?.format ?? text.format,
      versionNumber: source?.number ?? text.versionNumber,
      parts: parts.map((t, i) => ({
        text: t,
        charCount: xWeightedLength(t),
        charLimit: text.parts[i]?.charLimit ?? text.parts[0]?.charLimit ?? X_POST_MAX_CHARS,
      })),
      edited: !source || !sameParts(textsOf(source.parts), parts),
    };
  }

  private commit(parts: string[], kind: CommitKind, versionNumber: number) {
    const history = this.history;
    if (!history) return;
    const before = history.current.parts;
    this.report(history.commit(parts, kind, versionNumber).droppedRewrites);
    this.highlight(before, parts);
    if (kind === 'restore') this.announce(`Restored version ${versionNumber}`);
  }

  private report(count: number) {
    if (count === 0) return;
    this.deps.track('redo_rewrites_dropped', { count });
    this.droppedRewrites = { key: this.nextKey(), count };
  }

  private highlight(before: string[], after: string[]) {
    this.trace = { key: this.nextKey(), before, after };
  }

  private announce(message: string) {
    this.announcement = { key: this.nextKey(), message };
  }

  private nextKey() {
    this.keys += 1;
    return this.keys;
  }

  private emit() {
    this.current = this.build();
    this.listeners.forEach((listener) => listener());
  }

  private build(): TextSnapshot {
    const { text, versions, gate, writing, history } = this;
    const restoring = this.restoring !== null;
    const textChanges = gate.status === 'draft' || gate.status === 'failed';
    const edit = textChanges && !!text && gate.subscribed === true && !writing;
    const latest = versions[versions.length - 1];
    const source = text
      ? (versions.find((v) => v.number === text.versionNumber) ?? latest)
      : latest;
    return {
      text,
      versions,
      textVersion: text && source ? { ...source, format: text.format, parts: text.parts } : source,
      can: {
        edit,
        undo: edit && !restoring && !!history?.canUndo,
        redo: edit && !restoring && !!history?.canRedo,
        restore: textChanges && !writing && !restoring,
        sendFeedback: edit,
        postTo: textChanges && !writing,
      },
      writing,
      restoring,
      save: this.save,
      restoreError: this.restoreError,
      trace: this.trace,
      announcement: this.announcement,
      droppedRewrites: this.droppedRewrites,
    };
  }
}
