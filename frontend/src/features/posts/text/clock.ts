export type TimerId = unknown;

/** Time as the Text's saver and undo line read it, so tests can move it by hand. */
export interface Clock {
  now: () => number;
  setTimeout: (run: () => void, ms: number) => TimerId;
  clearTimeout: (id: TimerId) => void;
}

/** The browser's clock, read at each call so fake timers in tests still reach it. */
export const browserClock: Clock = {
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};
