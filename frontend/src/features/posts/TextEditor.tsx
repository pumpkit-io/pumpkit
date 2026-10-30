import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { IS_MAC } from '@/lib/shortcuts';
import { useMediaQuery } from '@/lib/useMediaQuery';
import { changeDiff, type PartChange } from './changeDiff';
import type { ShownPart } from './shownText';
import type { EditCause } from './textHistory';
import { TextCard } from './TextCard';
import type { TextTrace } from './useUndoLine';

/** How long the Pumpkin trace fades for, and how long it stays without a fade. */
export const TRACE_FADE_MS = 1_200;
export const TRACE_STILL_MS = 1_500;

/** What kind of change an edit was, from the browser's `inputType` ("insertText"…). */
export interface TextChange {
  cause: EditCause;
}

function causeOf(inputType: string | null, before: string, after: string): EditCause {
  if (inputType === 'insertLineBreak' || inputType === 'insertParagraph') return 'newline';
  if (inputType === 'insertFromPaste' || inputType === 'insertFromDrop') return 'paste';
  if (inputType === 'deleteByCut' || inputType === 'deleteByDrag') return 'cut';
  if (inputType?.startsWith('delete')) return 'deleting';
  if (inputType) return 'typing';
  return after.length < before.length ? 'deleting' : 'typing';
}

/** Where `before` and `after` differ: from `start` up to `end` in `before`. */
function changedSpan(before: string, after: string): { start: number; end: number } {
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start++;
  let end = before.length;
  let afterEnd = after.length;
  while (end > start && afterEnd > start && before[end - 1] === after[afterEnd - 1]) {
    end--;
    afterEnd--;
  }
  return { start, end };
}

/** A Part's changed words in the Pumpkin trace, laid exactly under the text the box shows. */
function Trace({ text, change }: { text: string; change: PartChange }) {
  const pieces: ReactNode[] = [];
  let at = 0;
  const points = [...change.deleted];
  const flushPoints = (upTo: number) => {
    while (points.length && points[0]! <= upTo) {
      const point = points.shift()!;
      pieces.push(text.slice(at, point));
      at = point;
      pieces.push(
        <span key={`point-${point}-${pieces.length}`} data-trace="" className="relative">
          <span className="absolute inset-y-0 -left-px w-0.5 rounded-full bg-primary" />
        </span>,
      );
    }
  };
  for (const range of change.inserted) {
    flushPoints(range.start);
    pieces.push(text.slice(at, range.start));
    pieces.push(
      <mark
        key={`mark-${range.start}`}
        data-trace=""
        className="rounded-sm bg-[var(--trace)] text-transparent"
      >
        {text.slice(range.start, range.end)}
      </mark>,
    );
    at = range.end;
  }
  flushPoints(text.length);
  pieces.push(text.slice(at));
  return <>{pieces}</>;
}

/** A Part's text as a box that looks like the post itself, growing with what it holds. */
function PartBox({
  label,
  value,
  onChange,
  onUndo,
  onRedo,
  trace,
}: {
  label: string;
  value: string;
  onChange: (value: string, inputType: string | null, caret: number) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  trace: { key: number; change: PartChange; first: boolean; still: boolean } | null;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const shown = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  const traceKey = trace?.first ? trace.key : null;
  const still = trace?.still ?? false;
  useEffect(() => {
    if (traceKey === null) return;
    shown.current
      ?.querySelector('[data-trace]')
      ?.scrollIntoView?.({ block: 'nearest', behavior: still ? 'auto' : 'smooth' });
  }, [traceKey, still]);

  return (
    <div className="relative -mx-2 -my-1">
      {trace && (
        <div
          ref={shown}
          aria-hidden
          className={`pointer-events-none absolute inset-0 whitespace-pre-wrap break-words px-2 py-1 font-sans text-[15px] leading-6 text-transparent ${trace.still ? '' : 'pumpkin-trace-fade'}`}
        >
          <Trace text={value} change={trace.change} />
        </div>
      )}
      <textarea
        ref={box}
        aria-label={label}
        aria-keyshortcuts={IS_MAC ? 'Meta+Z Meta+Shift+Z' : 'Control+Z Control+Shift+Z'}
        value={value}
        rows={1}
        onChange={(e) => {
          const native = e.nativeEvent as Partial<InputEvent>;
          onChange(e.target.value, native.inputType ?? null, e.target.selectionEnd);
        }}
        onKeyDown={(e) => {
          if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
          const key = e.key.toLowerCase();
          const redo = (key === 'z' && e.shiftKey) || (key === 'y' && !IS_MAC && !e.shiftKey);
          if (key !== 'z' && !redo) return;
          // The page keeps the undo line, so the browser's own undo would lose track of it.
          e.preventDefault();
          if (redo) onRedo?.();
          else onUndo?.();
        }}
        className="relative block w-full cursor-text resize-none overflow-hidden rounded-md bg-transparent px-2 py-1 font-sans text-[15px] leading-6 text-foreground outline-none ring-1 ring-transparent transition-shadow hover:ring-border focus:ring-primary motion-reduce:transition-none"
      />
    </div>
  );
}

/** The change from `trace` to mark in Pumpkin, for as long as the trace lasts. */
function useShownTrace(trace: TextTrace | null | undefined) {
  const still = useMediaQuery('(prefers-reduced-motion: reduce)');
  const [ended, setEnded] = useState<number | null>(null);
  const key = trace?.key ?? null;

  useEffect(() => {
    if (key === null) return;
    const timer = setTimeout(() => setEnded(key), still ? TRACE_STILL_MS : TRACE_FADE_MS);
    return () => clearTimeout(timer);
  }, [key, still]);

  const changes = useMemo(() => (trace ? changeDiff(trace.before, trace.after) : null), [trace]);
  if (!trace || !changes || ended === trace.key) return null;
  const first = changes.findIndex((c) => c.inserted.length > 0 || c.deleted.length > 0);
  return { key: trace.key, changes, first, still };
}

/**
 * The Post's card with each Part's text editable in place, except Parts live on X. `texts` are
 * the Text's Parts; an edit hands back all of them, so the number and order of Parts never change.
 * `trace` marks the words the last undo, redo, restore or rewrite changed.
 */
export function TextEditor({
  parts,
  texts,
  editable,
  onEdit,
  onUndo,
  onRedo,
  trace,
  corner,
  busy = false,
}: {
  /** What the card shows, the live Parts first on a Failed Post. */
  parts: ShownPart[];
  texts: string[];
  editable: boolean;
  onEdit: (texts: string[], change: TextChange) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  trace?: TextTrace | null;
  corner?: ReactNode;
  busy?: boolean;
}) {
  const total = parts.length;
  const caret = useRef<{ part: number; at: number } | null>(null);
  const shownTrace = useShownTrace(trace);

  const edit = (index: number, value: string, inputType: string | null, at: number) => {
    const before = texts[index] ?? '';
    const span = changedSpan(before, value);
    const last = caret.current;
    const jumped =
      last !== null && (last.part !== index || last.at < span.start || last.at > span.end);
    caret.current = { part: index, at };
    onEdit(
      texts.map((text, i) => (i === index ? value : text)),
      { cause: jumped ? 'cursorJump' : causeOf(inputType, before, value) },
    );
  };

  return (
    <TextCard
      parts={parts}
      busy={busy}
      corner={corner}
      renderText={
        editable
          ? (part, index) =>
              part.live ? undefined : (
                <PartBox
                  label={total > 1 ? `Part ${index + 1} text` : 'Post text'}
                  value={part.text}
                  onChange={(value, inputType, at) => edit(index, value, inputType, at)}
                  onUndo={onUndo}
                  onRedo={onRedo}
                  trace={
                    shownTrace?.changes[index]
                      ? {
                          key: shownTrace.key,
                          change: shownTrace.changes[index],
                          first: shownTrace.first === index,
                          still: shownTrace.still,
                        }
                      : null
                  }
                />
              )
          : undefined
      }
    />
  );
}
