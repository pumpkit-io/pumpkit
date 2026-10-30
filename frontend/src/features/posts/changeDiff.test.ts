import { describe, expect, it } from 'vitest';
import { changeDiff } from './changeDiff';

/** The inserted text in each Part, to read the ranges by what they cover. */
function insertedWords(after: string[], before: string[]) {
  return changeDiff(before, after).map((part, i) =>
    part.inserted.map(({ start, end }) => after[i]!.slice(start, end)),
  );
}

describe('changeDiff', () => {
  it('finds nothing to mark when the Text is the same', () => {
    expect(changeDiff(['Same words here'], ['Same words here'])).toEqual([
      { inserted: [], deleted: [] },
    ]);
  });

  it('marks inserted words by where they sit in the new text', () => {
    expect(changeDiff(['Ship it today'], ['Ship it early today'])).toEqual([
      { inserted: [{ start: 8, end: 13 }], deleted: [] },
    ]);
  });

  it('marks a run of inserted words as one range', () => {
    expect(insertedWords(['Ship it, then rest a little'], ['Ship it'])).toEqual([
      [', then rest a little'],
    ]);
  });

  it('marks a replaced word as inserted, not as a deletion too', () => {
    expect(changeDiff(['A good hook'], ['A great hook'])).toEqual([
      { inserted: [{ start: 2, end: 7 }], deleted: [] },
    ]);
  });

  it('marks where words were removed with a point', () => {
    expect(changeDiff(['Ship it really fast'], ['Ship it fast'])).toEqual([
      { inserted: [], deleted: [8] },
    ]);
  });

  it('marks removed words at the end of the text', () => {
    expect(changeDiff(['Ship it now'], ['Ship it'])).toEqual([{ inserted: [], deleted: [7] }]);
  });

  it('marks a change of whitespace alone with a point', () => {
    expect(changeDiff(['One\n\nTwo'], ['One Two'])).toEqual([{ inserted: [], deleted: [3] }]);
  });

  it('marks changes in each Part of a Thread on its own', () => {
    expect(
      changeDiff(
        ['First part', 'Second part', 'Third part'],
        ['First part', 'Second', 'Third bit'],
      ),
    ).toEqual([
      { inserted: [], deleted: [] },
      { inserted: [], deleted: [6] },
      { inserted: [{ start: 6, end: 9 }], deleted: [] },
    ]);
  });

  it('marks a whole new Part when a single post becomes a Thread', () => {
    expect(insertedWords(['Opening line', 'And a new part'], ['Opening line'])).toEqual([
      [],
      ['And a new part'],
    ]);
  });

  it('marks where a Part went when a Thread becomes a single post', () => {
    expect(changeDiff(['Opening line', 'Closing line'], ['Opening line Closing line'])).toEqual([
      { inserted: [], deleted: [12] },
    ]);
  });
});
