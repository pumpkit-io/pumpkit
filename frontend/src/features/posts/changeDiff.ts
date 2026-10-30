/** A run of characters in one Part, from `start` up to but not including `end`. */
export interface TextRange {
  start: number;
  end: number;
}

/** What changed in one Part of the new Text: the words put in, and where words were taken out. */
export interface PartChange {
  inserted: TextRange[];
  /** Offsets in the new text where removed words used to be. */
  deleted: number[];
}

/** Stands between Parts, so a Part boundary lines up like any word. */
const PART_BREAK = '\u0000';
/** Above this many comparisons, every changed Part is marked whole instead. */
const MAX_CELLS = 4_000_000;

const TOKEN = /\s+|[\p{L}\p{N}_'’]+|[^\s\p{L}\p{N}_'’]/gu;

function tokens(parts: readonly string[]): string[] {
  return parts.flatMap((part, i) => [...(i > 0 ? [PART_BREAK] : []), ...(part.match(TOKEN) ?? [])]);
}

const isWord = (token: string) => token !== PART_BREAK && !/^\s/.test(token);

type Op = { kind: 'keep' | 'insert' | 'delete'; token: string };

/** The shortest edit from `a` to `b`, removals placed before insertions where either fits. */
function editScript(a: string[], b: string[]): Op[] {
  const width = b.length + 1;
  // Longest common subsequence of every pair of suffixes.
  const lcs = new Uint32Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i * width + j] =
        a[i] === b[j]
          ? lcs[(i + 1) * width + j + 1]! + 1
          : Math.max(lcs[(i + 1) * width + j]!, lcs[i * width + j + 1]!);
    }
  }
  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      ops.push({ kind: 'keep', token: a[i++]! });
      j++;
    } else if (
      j >= b.length ||
      (i < a.length && lcs[(i + 1) * width + j]! >= lcs[i * width + j + 1]!)
    ) {
      ops.push({ kind: 'delete', token: a[i++]! });
    } else {
      ops.push({ kind: 'insert', token: b[j++]! });
    }
  }
  return ops;
}

function wholeParts(before: readonly string[], after: readonly string[]): PartChange[] {
  return after.map((text, i) => ({
    inserted: text === before[i] || !text ? [] : [{ start: 0, end: text.length }],
    deleted: [],
  }));
}

/**
 * What changed from `before` to `after`, word by word, per Part of `after`. A run of changes that
 * put words in marks those words; a run that only took words out, or changed only whitespace,
 * marks the point where it happened.
 */
export function changeDiff(before: readonly string[], after: readonly string[]): PartChange[] {
  const result: PartChange[] = after.map(() => ({ inserted: [], deleted: [] }));
  const a = tokens(before);
  const b = tokens(after);
  if ((a.length + 1) * (b.length + 1) > MAX_CELLS) return wholeParts(before, after);

  let part = 0;
  let offset = 0;
  let run: { part: number; offset: number; putWords: boolean; range: TextRange | null } | null =
    null;
  let rangePart = 0;

  const closeRange = () => {
    if (run?.range) result[rangePart]!.inserted.push(run.range);
    if (run) run.range = null;
  };
  const closeRun = () => {
    if (!run) return;
    closeRange();
    if (!run.putWords) result[run.part]!.deleted.push(run.offset);
    run = null;
  };
  const advance = (token: string) => {
    if (token === PART_BREAK) {
      part += 1;
      offset = 0;
    } else {
      offset += token.length;
    }
  };

  for (const op of editScript(a, b)) {
    if (op.kind === 'keep') {
      closeRun();
      advance(op.token);
      continue;
    }
    run ??= { part, offset, putWords: false, range: null };
    if (op.kind === 'delete') continue;
    if (isWord(op.token)) {
      run.putWords = true;
      if (run.range && rangePart === part) {
        run.range.end = offset + op.token.length;
      } else {
        closeRange();
        run.range = { start: offset, end: offset + op.token.length };
        rangePart = part;
      }
    }
    advance(op.token);
  }
  closeRun();
  return result;
}
