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
  /** Enter sends and Shift+Enter adds a newline, as in a chat, instead of ⌘Enter sending. */
  sendOnEnter?: boolean;
  /** Called with the send shortcut or the arrow, only when sending is possible. */
  onSend: () => void;
  /** Locks the box and the Format with the text kept, and turns the arrow into a spinner. */
  isWriting?: boolean;
  /** Keeps the arrow greyed out for a reason outside the text, such as data still loading. */
  sendDisabled?: boolean;
  /** Locks the box and the Format without a spinner, such as while the page loads. */
  disabled?: boolean;
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

/** The column a composer sits in, so the Brief and the Feedback boxes are always one size. */
export const COMPOSER_COLUMN = 'mx-auto w-full max-w-[53rem] px-4 sm:px-6';

/**
 * A box to write in that grows with its text, with the Format toggle at the bottom left and the
 * send arrow at the bottom right. Enter adds a newline and ⌘Enter or Ctrl+Enter sends, unless
 * `sendOnEnter` makes Enter send and Shift+Enter add the newline.
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
    sendOnEnter = false,
    onSend,
    isWriting = false,
    sendDisabled = false,
    disabled = false,
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
  const locked = isWriting || disabled;
  const canSend = !gate && typed && length <= maxLength && !sendDisabled && !locked;

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter that picks an IME candidate, such as for Japanese, isn't a send.
    if (e.key !== 'Enter' || e.nativeEvent.isComposing) return;
    if (sendOnEnter ? e.shiftKey : !(e.metaKey || e.ctrlKey)) return;
    e.preventDefault();
    if (canSend) onSend();
  };

  return (
    // No transition on focus: a box that mounts focused shows its line at once, not fading in.
    <div className="rounded-2xl border border-border bg-card shadow-glow focus-within:border-primary/50">
      <textarea
        ref={boxRef}
        aria-label={label}
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        rows={2}
        disabled={locked}
        style={{ maxHeight: maxRows * LINE_PX + PADDING_PX }}
        className="block w-full resize-none overflow-y-auto rounded-t-2xl bg-transparent px-4 pt-3 font-sans text-[15px] leading-6 text-foreground placeholder:text-muted-foreground focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 pb-3 pt-3">
        <FormatSelector value={format} onChange={onFormatChange} disabled={locked} hideLabel />
        <div className="ml-auto flex items-center gap-2">
          <LengthCounter length={length} max={maxLength} />
          {gate ?? (
            <button
              type="button"
              aria-label={isWriting ? 'Writing…' : sendLabel}
              aria-keyshortcuts={sendOnEnter ? 'Enter' : 'Meta+Enter Control+Enter'}
              onClick={onSend}
              disabled={!canSend}
              className={cn(
                'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card motion-reduce:transition-none',
                canSend
                  ? 'bg-foreground text-background hover:bg-foreground/85'
                  : 'cursor-not-allowed bg-muted text-muted-foreground',
              )}
            >
              {isWriting ? (
                <Loader2 className="h-5 w-5 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : (
                <ArrowUp className="h-5 w-5" aria-hidden />
              )}
            </button>
          )}
          {trailingAction}
        </div>
      </div>
    </div>
  );
});
