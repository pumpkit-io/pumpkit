import { useLayoutEffect, useRef, type ReactNode } from 'react';
import type { ShownPart } from './shownText';
import { TextCard } from './TextCard';

/** Which Part an edit changed, and how, as the browser's `inputType` says ("insertText"…). */
export interface TextChange {
  part: number;
  inputType: string | null;
}

/** A Part's text as a box that looks like the post itself, growing with what it holds. */
function PartBox({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string, inputType: string | null) => void;
}) {
  const box = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={box}
      aria-label={label}
      value={value}
      rows={1}
      onChange={(e) => {
        const native = e.nativeEvent as Partial<InputEvent>;
        onChange(e.target.value, native.inputType ?? null);
      }}
      className="-mx-2 -my-1 block w-[calc(100%+1rem)] cursor-text resize-none overflow-hidden rounded-md bg-transparent px-2 py-1 font-sans text-[15px] leading-6 text-foreground outline-none ring-1 ring-transparent transition-shadow hover:ring-border focus:ring-primary motion-reduce:transition-none"
    />
  );
}

/**
 * The Post's card with each Part's text editable in place, except Parts live on X. `texts` are
 * the Text's Parts; an edit hands back all of them, so the number and order of Parts never change.
 */
export function TextEditor({
  parts,
  texts,
  editable,
  onEdit,
  corner,
  busy = false,
}: {
  /** What the card shows, the live Parts first on a Failed Post. */
  parts: ShownPart[];
  texts: string[];
  editable: boolean;
  onEdit: (texts: string[], change: TextChange) => void;
  corner?: ReactNode;
  busy?: boolean;
}) {
  const total = parts.length;
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
                  onChange={(value, inputType) =>
                    onEdit(
                      texts.map((text, i) => (i === index ? value : text)),
                      { part: index, inputType },
                    )
                  }
                />
              )
          : undefined
      }
    />
  );
}
