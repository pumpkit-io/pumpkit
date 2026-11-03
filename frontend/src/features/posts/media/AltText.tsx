import { useId, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { ALT_TEXT_MAX_CHARS, type Media } from '@/services/mediaService';

const CHIP =
  'inline-flex h-6 items-center rounded-full px-2 font-sans text-xs font-semibold leading-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card';

/** Solid once the image is described: the fill of the tile's other controls. */
const SOLID = 'bg-foreground/75 text-background';
/** Hollow while it isn't: an opaque light pill, so it reads on any image, with a dashed edge. */
const HOLLOW = 'border border-dashed border-muted-foreground bg-card text-muted-foreground';

const SAVE_FAILED = "Couldn't save the alt text. Try again.";

const withCommas = (n: number) => n.toLocaleString('en-US');

/** A described image's chip where its alt text can't change, as on a Part already on X. */
export function AltTextMark({ media }: { media: Media }) {
  if (!media.altText) return null;
  // The image's own alt attribute carries the description to screen readers.
  return (
    <span aria-hidden className={cn(CHIP, SOLID, 'absolute bottom-1.5 left-1.5')}>
      Alt
    </span>
  );
}

/** The Alt chip on an image or GIF tile, opening a box to write, change or clear its alt text. */
export function AltTextChip({
  media,
  number,
  onSave,
}: {
  media: Media;
  number: number;
  /** Rejects when the server didn't take it; the popover then keeps the draft, even closed. */
  onSave: (altText: string | null) => Promise<void>;
}) {
  const id = useId();
  const box = useRef<HTMLTextAreaElement>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const described = media.altText !== null;

  const openChange = (next: boolean) => {
    // A save in flight decides whether the popover closes.
    if (saving) return;
    if (next && !failed) setDraft(media.altText ?? '');
    setOpen(next);
  };

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setFailed(false);
    try {
      await onSave(draft.trim() || null);
      setOpen(false);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Popover open={open} onOpenChange={openChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={
            described ? `Edit alt text of image ${number}` : `Add alt text to image ${number}`
          }
          className={cn(CHIP, described ? SOLID : HOLLOW, 'absolute bottom-1.5 left-1.5')}
        >
          Alt
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        aria-label={`Alt text for image ${number}`}
        className="w-[min(22rem,calc(100vw-2rem))] space-y-2 p-3"
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          box.current?.focus();
        }}
      >
        <label htmlFor={id} className="block font-sans text-sm font-medium text-foreground">
          Alt text
        </label>
        <Textarea
          ref={box}
          id={id}
          rows={4}
          maxLength={ALT_TEXT_MAX_CHARS}
          value={draft}
          readOnly={saving}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void save();
            }
          }}
          className="resize-none font-sans leading-6"
        />
        {failed && (
          <p role="alert" className="font-sans text-[13px] font-medium text-destructive">
            {SAVE_FAILED}
          </p>
        )}
        <div className="flex items-center justify-between gap-3">
          <span className="font-sans text-xs tabular-nums text-muted-foreground">
            {withCommas(draft.length)} / {withCommas(ALT_TEXT_MAX_CHARS)}
          </span>
          <Button
            type="button"
            variant="solid"
            size="sm"
            disabled={saving}
            onClick={() => void save()}
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
