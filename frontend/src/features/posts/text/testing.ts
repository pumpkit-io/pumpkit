import { xWeightedLength } from '@/lib/xLength';
import {
  formatOf,
  textOf,
  type Format,
  type PostDetail,
  type PostText,
  type Version,
} from '@/services/postService';
import { sameParts } from '../textHistory';
import type { Clock, TimerId } from './clock';
import type { TextBackend } from './textController';

/** Waits until every promise already settling has run its callbacks. */
export function settled(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/** An error as the API client throws it; no status is a request that never reached the server. */
export function httpError(status: number | null, detail?: string) {
  return Object.assign(
    new Error(status ? `Request failed with status code ${status}` : 'Network Error'),
    {
      isAxiosError: true,
      response: status ? { status, data: detail ? { detail } : {} } : undefined,
    },
  );
}

/** A clock that moves only when `advance` says, running each timer that falls due in order. */
export class ManualClock implements Clock {
  private at = 0;
  private nextId = 1;
  private timers = new Map<number, { due: number; run: () => void }>();

  now = () => this.at;

  setTimeout = (run: () => void, ms: number): TimerId => {
    const id = this.nextId++;
    this.timers.set(id, { due: this.at + ms, run });
    return id;
  };

  clearTimeout = (id: TimerId) => {
    this.timers.delete(id as number);
  };

  /** Moves time on by `ms`, letting the promises each timer starts settle before the next. */
  async advance(ms: number): Promise<void> {
    const until = this.at + ms;
    for (;;) {
      await settled();
      const due = [...this.timers]
        .filter(([, timer]) => timer.due <= until)
        .sort(([, a], [, b]) => a.due - b.due)[0];
      if (!due) break;
      const [id, timer] = due;
      this.timers.delete(id);
      this.at = timer.due;
      timer.run();
    }
    this.at = until;
    await settled();
  }
}

type Method = keyof TextBackend;

/** A call held open by `hold`, until the test lets it land or fails it. */
export interface HeldCall {
  release: () => Promise<void>;
  fail: (error: unknown) => Promise<void>;
}

/**
 * One Post's Text and Versions held the way the server holds them, behind the controller's
 * backend port. A call changes them only when it lands, so a held call changes nothing yet.
 */
export class MemoryBackend {
  versions: Version[];
  text: PostText | null;
  readonly calls: { method: Method; args: unknown[] }[] = [];
  /** The Parts the next Version written from Feedback gets, else one Part naming the Feedback. */
  nextRewrite: string[] | null = null;
  private failures: { method: Method; error: unknown }[] = [];
  private holds: { method: Method; call: Promise<'release' | { error: unknown }> }[] = [];

  constructor(post: PostDetail) {
    this.versions = [...post.versions];
    this.text = post.text;
  }

  get textParts(): string[] {
    return this.text?.parts.map((p) => p.text) ?? [];
  }

  callsOf(method: Method): unknown[][] {
    return this.calls.filter((c) => c.method === method).map((c) => c.args);
  }

  failNext(method: Method, error: unknown, times = 1) {
    for (let i = 0; i < times; i++) this.failures.push({ method, error });
  }

  /** The held call lands or fails only when the test says, with the server as it is then. */
  hold(method: Method): HeldCall {
    let answer: (outcome: 'release' | { error: unknown }) => void = () => {};
    const call = new Promise<'release' | { error: unknown }>((resolve) => (answer = resolve));
    this.holds.push({ method, call });
    return {
      release: async () => {
        answer('release');
        await settled();
      },
      fail: async (error) => {
        answer({ error });
        await settled();
      },
    };
  }

  readonly port: TextBackend = {
    saveText: (parts) =>
      this.answer('saveText', [parts], () => {
        const text = this.text!;
        const version = this.versions.find((v) => v.number === text.versionNumber)!;
        this.text = {
          format: formatOf(parts),
          parts: parts.map((t, i) => ({
            text: t,
            charCount: xWeightedLength(t),
            charLimit: text.parts[i]?.charLimit ?? text.parts[0]!.charLimit,
          })),
          versionNumber: text.versionNumber,
          edited: !sameParts(
            parts,
            version.parts.map((p) => p.text),
          ),
        };
        return this.text;
      }),
    restoreVersion: (versionNumber) =>
      this.answer('restoreVersion', [versionNumber], () => {
        const version = this.versions.find((v) => v.number === versionNumber);
        if (!version) throw httpError(404, 'No such version.');
        this.text = textOf(version);
        return this.text;
      }),
    addVersion: (feedback: string, format: Format, parts: string[]) =>
      this.answer('addVersion', [feedback, format, parts], () => {
        if (!sameParts(parts, this.textParts))
          throw httpError(409, 'The text changed since. Reload the post.');
        const texts = this.nextRewrite ?? [`rewritten: ${feedback}`];
        this.nextRewrite = null;
        const number = this.versions.length + 1;
        const version: Version = {
          id: `version_${number}`,
          number,
          feedback,
          format: formatOf(texts),
          parts: texts.map((t) => ({ text: t, charCount: xWeightedLength(t), charLimit: 280 })),
          createdAt: '2026-10-31T10:00:00Z',
        };
        this.versions = [...this.versions, version];
        this.text = textOf(version);
        return version;
      }),
  };

  private async answer<T>(method: Method, args: unknown[], land: () => T): Promise<T> {
    this.calls.push({ method, args });
    const hold = this.holds.findIndex((h) => h.method === method);
    const held = hold >= 0 ? this.holds.splice(hold, 1)[0]! : null;
    const failure = this.failures.findIndex((f) => f.method === method);
    const failed = failure >= 0 ? this.failures.splice(failure, 1)[0]! : null;
    const outcome = held ? await held.call : 'release';
    if (outcome !== 'release') throw outcome.error;
    if (failed) throw failed.error;
    return land();
  }
}
