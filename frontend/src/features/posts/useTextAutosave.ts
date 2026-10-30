import { useCallback, useEffect, useMemo, useState } from 'react';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { formatOf, postService } from '@/services/postService';

/** How long the User stops typing before their edit is saved. */
export const TEXT_SAVE_PAUSE_MS = 800;
/** The wait before retrying a failed save, doubling with each failure up to a ceiling. */
export const TEXT_SAVE_RETRY_MS = 2_000;
const MAX_RETRY_MS = 30_000;

export type TextSaveState =
  | { kind: 'saved' }
  /** Waiting for the pause, or on its way to the server. */
  | { kind: 'pending' }
  | { kind: 'retrying' }
  /** The server turned the edit down, so retrying it as it is won't help. */
  | { kind: 'refused'; message: string };

/** A 4xx turns the edit down for good, except a timeout or a rate limit. */
function refusesForGood(e: unknown): boolean {
  const status = errorStatus(e);
  return status !== null && status >= 400 && status < 500 && status !== 408 && status !== 429;
}

/**
 * Sends one Post's Text edits to the server, one save at a time: each burst of edits once the
 * User pauses, and the latest edit again after a failure. Saving is idempotent, so a retry sends
 * the same Parts as they are.
 */
class TextSaver {
  private unsaved: string[] | null = null;
  private sending: Promise<void> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private failures = 0;
  private retrying = false;
  private waiting: ((saved: boolean) => void)[] = [];

  constructor(
    private readonly save: (parts: string[]) => Promise<unknown>,
    private readonly onState: (state: TextSaveState) => void,
    private readonly onSaved: (parts: string[]) => void,
  ) {}

  edit(parts: string[]) {
    this.unsaved = parts;
    // A pending retry sends the latest Parts when it fires.
    if (this.retrying) return;
    this.onState({ kind: 'pending' });
    this.sendIn(TEXT_SAVE_PAUSE_MS);
  }

  /** Saves at once; true once the server has every edit, false if it refused one. */
  flush(): Promise<boolean> {
    if (!this.unsaved && !this.sending) return Promise.resolve(true);
    const done = new Promise<boolean>((resolve) => this.waiting.push(resolve));
    // A pending retry goes now too: the User is waiting on it.
    void this.send();
    return done;
  }

  /** Drops the edits not yet sent and waits for one already out, before the Text is replaced. */
  async discard(): Promise<void> {
    this.clearTimer();
    this.unsaved = null;
    this.retrying = false;
    this.failures = 0;
    this.onState({ kind: 'saved' });
    this.settle(true);
    await this.sending;
  }

  /** Sends what the pause was still holding back, as the page goes away. */
  dispose() {
    this.clearTimer();
    if (this.unsaved && !this.sending) void this.save(this.unsaved).catch(() => {});
  }

  private sendIn(ms: number) {
    this.clearTimer();
    this.timer = setTimeout(() => void this.send(), ms);
  }

  private clearTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private settle(saved: boolean) {
    const waiting = this.waiting;
    this.waiting = [];
    waiting.forEach((done) => done(saved));
  }

  private async send(): Promise<void> {
    this.clearTimer();
    // The save out now sends the rest when it lands.
    if (this.sending) return;
    const parts = this.unsaved;
    if (!parts) {
      this.settle(true);
      return;
    }
    this.sending = this.attempt(parts);
    await this.sending;
    this.sending = null;
    // An edit made while the save was out, whose pause ran out meanwhile.
    if (this.unsaved && this.unsaved !== parts && !this.timer) void this.send();
  }

  private async attempt(parts: string[]): Promise<void> {
    try {
      await this.save(parts);
    } catch (e) {
      // A newer edit replaces this one, so its own save decides.
      if (this.unsaved !== parts) return;
      if (refusesForGood(e)) {
        this.retrying = false;
        this.onState({ kind: 'refused', message: errorMessage(e, "Couldn't save your edit.") });
        this.settle(false);
        return;
      }
      this.retrying = true;
      this.onState({ kind: 'retrying' });
      this.sendIn(Math.min(TEXT_SAVE_RETRY_MS * 2 ** this.failures, MAX_RETRY_MS));
      this.failures += 1;
      return;
    }
    this.failures = 0;
    this.retrying = false;
    this.onSaved(parts);
    if (this.unsaved !== parts) return;
    this.unsaved = null;
    this.onState({ kind: 'saved' });
    this.settle(true);
  }
}

/**
 * Autosave for a Post's Text: `edit` takes every Part after each change, `flush` saves at once
 * and resolves true once nothing is left unsaved, and `discard` drops what isn't sent yet.
 * A saved burst is tracked once, retries included.
 */
export function useTextAutosave(postId: string) {
  const [state, setState] = useState<TextSaveState>({ kind: 'saved' });
  const saver = useMemo(
    () =>
      new TextSaver(
        (parts) => postService.saveText(postId, parts),
        setState,
        (parts) => track('post_text_edited', { format: formatOf(parts), part_count: parts.length }),
      ),
    [postId],
  );

  useEffect(() => () => saver.dispose(), [saver]);

  const edit = useCallback((parts: string[]) => saver.edit(parts), [saver]);
  const flush = useCallback(() => saver.flush(), [saver]);
  const discard = useCallback(() => saver.discard(), [saver]);

  return { state, edit, flush, discard };
}
