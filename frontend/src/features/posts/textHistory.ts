/** How long the User stops typing before their next keystroke starts a new undo step. */
export const BURST_PAUSE_MS = 1_000;

/** What kind of change an edit was, as the editor tells it. */
export type EditCause = 'typing' | 'deleting' | 'newline' | 'paste' | 'cut' | 'cursorJump';

/** A change Pumpkit made to the Text: a rewrite from Feedback, or a Version restored from History. */
export type CommitKind = 'rewrite' | 'restore';

/** Where a step's Text came from: the Version, and whether the User changed it since. */
export interface TextOrigin {
  versionNumber: number;
  edited: boolean;
}

/** One place on the undo line: the Text's Parts there, and the change that led to it. */
export interface TextStep {
  kind: 'start' | 'edit' | CommitKind;
  parts: string[];
  origin: TextOrigin;
}

/** A move along the line: the step undone or redone, and the step now current. */
export interface TextMove {
  step: TextStep;
  current: TextStep;
}

/** What a new step cost: the rewrites it dropped from redo, which History still holds. */
export interface TextRecord {
  droppedRewrites: number;
}

interface Step extends TextStep {
  /** The Version's own Parts, to tell whether an edit brought the Text back to it. */
  versionParts: string[];
}

interface Burst {
  mode: 'typing' | 'deleting' | null;
  lastAt: number;
  /** A paste or a cut stands alone, so the next edit starts a step of its own. */
  closed: boolean;
}

const sameParts = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((text, i) => text === b[i]);

const modeOf = (cause: EditCause): Burst['mode'] =>
  cause === 'deleting' ? 'deleting' : cause === 'typing' || cause === 'newline' ? 'typing' : null;

/**
 * The undo line for one Post's Text, in one browser tab: the User's typing grouped into bursts,
 * and each rewrite and restore as a step of its own. One straight line: a new step drops the
 * steps redo would have reached.
 */
export class TextHistory {
  private steps: Step[];
  private index = 0;
  private burst: Burst | null = null;

  constructor(
    start: { parts: string[]; versionNumber: number; versionParts: string[] },
    private readonly clock: { now: () => number },
    private readonly pauseMs = BURST_PAUSE_MS,
  ) {
    this.steps = [
      {
        kind: 'start',
        parts: [...start.parts],
        versionParts: [...start.versionParts],
        origin: {
          versionNumber: start.versionNumber,
          edited: !sameParts(start.parts, start.versionParts),
        },
      },
    ];
  }

  get current(): TextStep {
    return this.public(this.steps[this.index]!);
  }

  get canUndo(): boolean {
    return this.index > 0;
  }

  get canRedo(): boolean {
    return this.index < this.steps.length - 1;
  }

  /** Records the User's change to the Text, as part of the burst they're typing or as a new step. */
  edit(next: string[], cause: EditCause): TextRecord {
    const at = this.steps[this.index]!;
    if (sameParts(next, at.parts)) return { droppedRewrites: 0 };
    const now = this.clock.now();
    const mode = modeOf(cause);
    const burst = this.burst;
    const continues =
      burst !== null &&
      !burst.closed &&
      now - burst.lastAt < this.pauseMs &&
      cause !== 'newline' &&
      mode !== null &&
      (burst.mode === null || burst.mode === mode);

    this.burst = {
      mode: mode ?? null,
      lastAt: now,
      closed: cause === 'paste' || cause === 'cut',
    };
    const origin = {
      versionNumber: at.origin.versionNumber,
      edited: !sameParts(next, at.versionParts),
    };
    if (continues) {
      this.steps[this.index] = { ...at, parts: [...next], origin };
      return { droppedRewrites: 0 };
    }
    return this.push({ kind: 'edit', parts: [...next], versionParts: at.versionParts, origin });
  }

  /** Records a rewrite from Feedback or a restore from History as its own step. */
  commit(parts: string[], kind: CommitKind, versionNumber: number): TextRecord {
    this.burst = null;
    return this.push({
      kind,
      parts: [...parts],
      versionParts: [...parts],
      origin: { versionNumber, edited: false },
    });
  }

  undo(): TextMove | null {
    if (!this.canUndo) return null;
    this.burst = null;
    const step = this.steps[this.index]!;
    this.index -= 1;
    return { step: this.public(step), current: this.current };
  }

  redo(): TextMove | null {
    if (!this.canRedo) return null;
    this.burst = null;
    this.index += 1;
    const step = this.current;
    return { step, current: step };
  }

  private push(step: Step): TextRecord {
    const dropped = this.steps.slice(this.index + 1);
    this.steps = [...this.steps.slice(0, this.index + 1), step];
    this.index = this.steps.length - 1;
    return { droppedRewrites: dropped.filter((s) => s.kind === 'rewrite').length };
  }

  private public({ kind, parts, origin }: Step): TextStep {
    return { kind, parts: [...parts], origin: { ...origin } };
  }
}
