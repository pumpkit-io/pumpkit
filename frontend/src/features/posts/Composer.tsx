import {
  forwardRef,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';
import { charCount } from '@/lib/characters';
import { MOD_LABEL } from '@/lib/shortcuts';
import { cn } from '@/lib/utils';
import type { Format } from '@/services/postService';
import { FormatSelector } from './FormatSelector';
import { LengthCounter } from './LengthCounter';

export interface ComposerProps {
  /** The box's accessible name, such as "Brief" or "Feedback"; it is never shown. */
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  format: Format;
  onFormatChange: (format: Format) => void;
  /** Characters allowed; the counter shows only near it, and sending stops past it. */
  maxLength: number;
  /** The send arrow's accessible name. */
  sendLabel: string;
  /** Ends the shortcut hint, as in "⌘↵ to write". */
  shortcutVerb: string;
  /** Called with ⌘Enter, Ctrl+Enter or the arrow, only when sending is possible. */
  onSend: () => void;
  /** Locks the box and the Format with the text kept, and turns the arrow into a spinner. */
  isWriting?: boolean;
  /** Keeps the arrow greyed out for a reason outside the text, such as data still loading. */
  sendDisabled?: boolean;
  /** Takes the arrow's place when the User can't send yet, such as "Subscribe to write". */
  gate?: ReactNode;
  /** After the arrow, such as "Post to…". */
  trailingAction?: ReactNode;
  /** Lines the box grows to before it scrolls inside. */
  maxRows?: number;
  autoFocus?: boolean;
}

const LINE_PX = 24;
const PADDING_PX = 24;

/**
 * A box to write in that grows with its text, with the Format toggle at the bottom left and the
 * send arrow at the bottom right. Enter adds a newline; ⌘Enter or Ctrl+Enter sends.
 */
export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  {
    label,
    placeholder,
    value,
    onChange,
    format,
    onFormatChange,
    maxLength,
    sendLabel,
    shortcutVerb,
    onSend,
    isWriting = false,
    sendDisabled = false,
    gate,
    trailingAction,
    maxRows = 12,
    autoFocus = false,
  },
  ref,
) {
  const boxRef = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => boxRef.current as HTMLTextAreaElement);

  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    box.style.height = 'auto';
    box.style.height = `${box.scrollHeight}px`;
  }, [value]);

  const typed = value.trim() !== '';
  const length = charCount(value);
  const canSend = !gate && typed && length <= maxLength && !sendDisabled && !isWriting;

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter' || !(e.metaKey || e.ctrlKey)) return;
    e.preventDefault();
    if (canSend) onSend();
  };

  return (
    <div className="rounded-2xl border border-border bg-card shadow-panel transition-[border-color,box-shadow] focus-within:border-primary focus-within:ring-[3px] focus-within:ring-primary/20 motion-reduce:transition-none">
      <textarea
        ref={boxRef}
        aria-label={label}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        rows={2}
        disabled={isWriting}
        style={{ maxHeight: maxRows * LINE_PX + PADDING_PX }}
        className="block w-full resize-none overflow-y-auto rounded-t-2xl bg-transparent px-4 pt-3 font-sans text-[15px] leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 pb-3 pt-1">
        <FormatSelector value={format} onChange={onFormatChange} disabled={isWriting} hideLabel />
        <div className="ml-auto flex items-center gap-2">
          <LengthCounter length={length} max={maxLength} />
          {gate ?? (
            <>
              {typed && !isWriting && (
                <span
                  aria-hidden
                  className="font-sans text-[13px] tabular-nums text-muted-foreground"
                >
                  {MOD_LABEL}↵ to {shortcutVerb}
                </span>
              )}
              <button
                type="button"
                aria-label={isWriting ? 'Writing…' : sendLabel}
                aria-keyshortcuts="Meta+Enter Control+Enter"
                onClick={onSend}
                disabled={!canSend}
                className={cn(
                  'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card motion-reduce:transition-none',
                  canSend
                    ? 'bg-foreground text-background hover:bg-foreground/85'
                    : 'cursor-not-allowed bg-muted text-muted-foreground',
                )}
              >
                {isWriting ? (
                  <Loader2
                    className="h-5 w-5 animate-spin motion-reduce:animate-none"
                    aria-hidden
                  />
                ) : (
                  <ArrowUp className="h-5 w-5" aria-hidden />
                )}
              </button>
            </>
          )}
          {trailingAction}
        </div>
      </div>
    </div>
  );
});
