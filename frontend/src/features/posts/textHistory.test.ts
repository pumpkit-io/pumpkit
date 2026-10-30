import { describe, expect, it } from 'vitest';
import { TextHistory } from './textHistory';

function historyAt(parts: string[] = ['Hello'], versionNumber = 1) {
  const clock = { t: 0 };
  const history = new TextHistory(
    { parts, versionNumber, versionParts: parts },
    { now: () => clock.t },
  );
  return { history, clock };
}

describe('TextHistory', () => {
  it('undoes a burst of typing in one step', () => {
    const { history, clock } = historyAt();
    history.edit(['Hello w'], 'typing');
    clock.t += 200;
    history.edit(['Hello wo'], 'typing');
    clock.t += 200;
    history.edit(['Hello wor'], 'typing');

    expect(history.canUndo).toBe(true);
    history.undo();

    expect(history.current.parts).toEqual(['Hello']);
    expect(history.canUndo).toBe(false);
  });

  it.each([
    ['a pause of a second', 'typing', 1_000],
    ['a newline', 'newline', 100],
    ['a paste', 'paste', 100],
    ['a cut', 'cut', 100],
    ['a switch to deleting', 'deleting', 100],
    ['a cursor jump', 'cursorJump', 100],
  ] as const)('starts a new step on %s', (_rule, cause, wait) => {
    const { history, clock } = historyAt();
    history.edit(['Hello there'], 'typing');
    clock.t += wait;
    history.edit(['Hello there!'], cause);

    history.undo();
    expect(history.current.parts).toEqual(['Hello there']);
    history.undo();
    expect(history.current.parts).toEqual(['Hello']);
  });

  it('keeps typing after a pause shorter than a second in the same step', () => {
    const { history, clock } = historyAt();
    history.edit(['Hello t'], 'typing');
    clock.t += 999;
    history.edit(['Hello th'], 'typing');

    history.undo();
    expect(history.current.parts).toEqual(['Hello']);
  });

  it('starts a new step on a switch from deleting back to typing', () => {
    const { history, clock } = historyAt();
    history.edit(['Hell'], 'deleting');
    clock.t += 100;
    history.edit(['Hel'], 'deleting');
    clock.t += 100;
    history.edit(['Help'], 'typing');

    history.undo();
    expect(history.current.parts).toEqual(['Hel']);
    history.undo();
    expect(history.current.parts).toEqual(['Hello']);
  });

  it("keeps typing on after a newline in the newline's step", () => {
    const { history, clock } = historyAt();
    history.edit(['Hello\n'], 'newline');
    clock.t += 100;
    history.edit(['Hello\nW'], 'typing');

    history.undo();
    expect(history.current.parts).toEqual(['Hello']);
  });

  it('makes the edit after a paste a step of its own', () => {
    const { history, clock } = historyAt();
    history.edit(['Hello pasted'], 'paste');
    clock.t += 100;
    history.edit(['Hello pasted!'], 'typing');

    history.undo();
    expect(history.current.parts).toEqual(['Hello pasted']);
  });

  it('keeps typing after a cursor jump in the jump’s step', () => {
    const { history, clock } = historyAt();
    history.edit(['XHello'], 'cursorJump');
    clock.t += 100;
    history.edit(['XYHello'], 'typing');

    history.undo();
    expect(history.current.parts).toEqual(['Hello']);
  });

  it('records a rewrite and a restore as one step each, with the Version they came from', () => {
    const { history, clock } = historyAt(['V1 text']);
    history.edit(['V1 text, edited'], 'typing');
    history.commit(['V2 text'], 'rewrite', 2);
    clock.t += 100;
    history.commit(['V1 text'], 'restore', 1);

    expect(history.current).toEqual({
      kind: 'restore',
      parts: ['V1 text'],
      origin: { versionNumber: 1, edited: false },
    });
    expect(history.undo()?.step.kind).toBe('restore');
    expect(history.current.origin).toEqual({ versionNumber: 2, edited: false });
    expect(history.undo()?.step.kind).toBe('rewrite');
    expect(history.current).toEqual({
      kind: 'edit',
      parts: ['V1 text, edited'],
      origin: { versionNumber: 1, edited: true },
    });
  });

  it('starts typing after a rewrite in a new step', () => {
    const { history, clock } = historyAt();
    history.commit(['Rewritten'], 'rewrite', 2);
    clock.t += 100;
    history.edit(['Rewritten!'], 'typing');

    history.undo();
    expect(history.current.parts).toEqual(['Rewritten']);
  });

  it('reads an edit back to the exact text of its Version as unedited', () => {
    const { history, clock } = historyAt(['Hi']);
    history.edit(['Hi!'], 'typing');
    clock.t += 1_500;
    history.edit(['Hi'], 'deleting');

    expect(history.current.origin).toEqual({ versionNumber: 1, edited: false });
    history.undo();
    expect(history.current.origin).toEqual({ versionNumber: 1, edited: true });
  });

  it('starts from a Text the User already edited, as edited', () => {
    const history = new TextHistory(
      { parts: ['Mine'], versionNumber: 3, versionParts: ["Pumpkit's"] },
      { now: () => 0 },
    );
    expect(history.current.origin).toEqual({ versionNumber: 3, edited: true });
    history.edit(["Pumpkit's"], 'paste');
    expect(history.current.origin).toEqual({ versionNumber: 3, edited: false });
  });

  it('redoes what was undone, in order, and ends at the newest step', () => {
    const { history } = historyAt();
    history.edit(['Hello!'], 'typing');
    history.commit(['Rewritten'], 'rewrite', 2);
    history.undo();
    history.undo();

    expect(history.canRedo).toBe(true);
    expect(history.redo()?.current.parts).toEqual(['Hello!']);
    expect(history.redo()?.step).toEqual({
      kind: 'rewrite',
      parts: ['Rewritten'],
      origin: { versionNumber: 2, edited: false },
    });
    expect(history.canRedo).toBe(false);
  });

  it('does nothing at either end of the line', () => {
    const { history } = historyAt();
    expect(history.undo()).toBeNull();
    expect(history.redo()).toBeNull();
    expect(history.current.parts).toEqual(['Hello']);
  });

  it('starts a new step on typing right after an undo, dropping redo', () => {
    const { history, clock } = historyAt();
    history.edit(['Hello wo'], 'typing');
    clock.t += 1_500;
    history.edit(['Hello world'], 'typing');
    history.undo();
    clock.t += 100;

    expect(history.edit(['Hello wox'], 'typing')).toEqual({ droppedRewrites: 0 });
    expect(history.canRedo).toBe(false);
    history.undo();
    expect(history.current.parts).toEqual(['Hello wo']);
  });

  it('reports the rewrites a new step dropped from redo', () => {
    const { history } = historyAt();
    history.commit(['V2'], 'rewrite', 2);
    history.commit(['V1'], 'restore', 1);
    history.commit(['V3'], 'rewrite', 3);
    history.undo();
    history.undo();
    history.undo();

    expect(history.edit(['Hello?'], 'typing')).toEqual({ droppedRewrites: 2 });
  });

  it('reports no dropped rewrites when redo held only edits and restores', () => {
    const { history, clock } = historyAt();
    history.edit(['Hello!'], 'typing');
    clock.t += 100;
    history.commit(['V1'], 'restore', 1);
    history.undo();
    history.undo();

    expect(history.commit(['V2'], 'rewrite', 2)).toEqual({ droppedRewrites: 0 });
    expect(history.canRedo).toBe(false);
  });

  it('records nothing for an edit that leaves the Text as it is', () => {
    const { history } = historyAt();
    history.edit(['Hello'], 'typing');
    expect(history.canUndo).toBe(false);
  });

  it('steps a Thread through all its Parts at once', () => {
    const { history, clock } = historyAt(['One', 'Two']);
    history.edit(['One', 'Two!'], 'typing');
    clock.t += 100;
    history.edit(['One?', 'Two!'], 'cursorJump');

    history.undo();
    expect(history.current.parts).toEqual(['One', 'Two!']);
    history.undo();
    expect(history.current.parts).toEqual(['One', 'Two']);
  });

  it('rewinds to a mark, undoing the moves and edits made since', () => {
    const { history, clock } = historyAt();
    history.commit(['V2'], 'rewrite', 2);
    clock.t += 100;
    history.edit(['V2, typed'], 'typing');
    const mark = history.mark();
    history.undo();
    history.undo();
    clock.t += 100;
    history.edit(['Hello, typed'], 'typing');

    history.rewind(mark);

    expect(history.current).toEqual({
      kind: 'edit',
      parts: ['V2, typed'],
      origin: { versionNumber: 2, edited: true },
    });
    expect(history.canRedo).toBe(false);
    history.undo();
    expect(history.current.parts).toEqual(['V2']);
  });

  it('starts a new step on typing right after a rewind', () => {
    const { history, clock } = historyAt();
    history.edit(['Hello!'], 'typing');
    const mark = history.mark();
    history.rewind(mark);
    clock.t += 100;
    history.edit(['Hello!?'], 'typing');

    history.undo();
    expect(history.current.parts).toEqual(['Hello!']);
  });
});
