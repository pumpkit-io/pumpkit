import * as DialogPrimitive from '@radix-ui/react-dialog';
import { ChevronLeft, ChevronRight, Film, Image as ImageIcon, Loader2, X } from 'lucide-react';
import type { KeyboardEvent, MouseEvent, RefObject, SyntheticEvent } from 'react';
import {
  Dialog,
  DialogClose,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import type { Media, MediaKind } from '@/services/mediaService';
import { mediaNoun } from './mediaRules';
import { useMediaFile, useMediaPreview } from './useMediaPreview';

/** One Media the view can show, as its tile has it. */
export interface Viewable {
  key: string;
  /** As the tile is named: "Image 2", "GIF 1". */
  name: string;
  kind: MediaKind;
  /** Null while it is still uploading. */
  media: Media | null;
  /** The file already in the browser, or a video's first frame, from an upload in this session. */
  localUrl: string | null;
}

const VIEW_BUTTON =
  'inline-flex h-10 w-10 items-center justify-center rounded-full bg-foreground/75 text-background transition-colors hover:bg-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background motion-reduce:transition-none';

const FADE =
  'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 motion-reduce:!animate-none';

function FullSizeMedia({ item, number }: { item: Viewable; number: number }) {
  // A video's copy in the browser is only its first frame, so its file still comes from the server.
  const localFile = item.kind === 'video' ? null : item.localUrl;
  const file = useMediaFile(localFile ? null : (item.media?.id ?? null));
  const full = localFile ?? file.url;
  const preview = useMediaPreview(full || item.localUrl ? null : (item.media?.previewUrl ?? null));
  const still = item.localUrl ?? preview.url;
  const downloading = full === null && item.media !== null && !file.failed;
  const altText = item.media?.altText ?? null;
  const KindIcon = item.kind === 'video' ? Film : ImageIcon;
  return (
    <figure className="flex max-w-[90vw] flex-col items-center gap-3">
      <div className="relative">
        {full && item.kind === 'video' ? (
          <video
            src={full}
            controls
            playsInline
            aria-label={item.name}
            className="max-h-[80vh] max-w-[90vw]"
          />
        ) : (full ?? still) ? (
          <img
            src={full ?? still ?? undefined}
            alt={altText ?? ''}
            className="max-h-[80vh] max-w-[90vw] object-contain"
          />
        ) : (
          (preview.failed || !item.media?.previewUrl) && (
            <div
              role="img"
              aria-label={item.name}
              className="flex aspect-video w-[min(90vw,32rem)] items-center justify-center rounded-2xl bg-muted text-muted-foreground"
            >
              <KindIcon aria-hidden className="h-8 w-8" />
            </div>
          )
        )}
        {downloading && item.kind !== 'image' && (
          <div
            role="status"
            aria-label={`Loading ${mediaNoun(item.kind)} ${number}`}
            className="absolute inset-0 flex items-center justify-center"
          >
            <span className={VIEW_BUTTON}>
              <Loader2 aria-hidden className="h-5 w-5 animate-spin motion-reduce:animate-none" />
            </span>
          </div>
        )}
      </div>
      {altText && (
        <figcaption
          aria-hidden
          className="max-w-prose text-center font-sans text-[13px] leading-5 text-background/80"
        >
          {altText}
        </figcaption>
      )}
    </figure>
  );
}

/**
 * A Part's Media full size, one at a time, opened on `openKey`; read-only, so alt text and
 * removing stay on the tiles. Moving stops at either end rather than wrapping.
 */
export function MediaView({
  items,
  openKey,
  onOpenKeyChange,
  returnFocus,
}: {
  items: Viewable[];
  /** The key of the Media shown, or null while closed. */
  openKey: string | null;
  onOpenKeyChange: (key: string | null) => void;
  /** The tile the view opened from, focused again once it closes. */
  returnFocus: RefObject<HTMLElement | null>;
}) {
  const index = items.findIndex((item) => item.key === openKey);
  const item = index >= 0 ? items[index] : undefined;
  const previous = index > 0 ? items[index - 1] : undefined;
  const next = index >= 0 ? items[index + 1] : undefined;

  const onKeyDown = (event: KeyboardEvent) => {
    const to = event.key === 'ArrowLeft' ? previous : event.key === 'ArrowRight' ? next : undefined;
    if (to) onOpenKeyChange(to.key);
  };

  // A click anywhere but the Media or a control closes it, as one on the backdrop would.
  const onBackgroundClick = (event: MouseEvent) => {
    if (!(event.target as Element).closest('img, video, [role="img"], button'))
      onOpenKeyChange(null);
  };

  // React bubbles events through the portal, so a drop here would reach the Part's drop target behind.
  const keepInside = (event: SyntheticEvent) => event.stopPropagation();

  return (
    <Dialog open={item !== undefined} onOpenChange={(open) => !open && onOpenKeyChange(null)}>
      <DialogPortal>
        <DialogOverlay className="bg-foreground/90 backdrop-blur-none motion-reduce:!animate-none" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          onKeyDown={onKeyDown}
          onClick={onBackgroundClick}
          onDragEnter={keepInside}
          onDragOver={keepInside}
          onDragLeave={keepInside}
          onDrop={keepInside}
          // Radix can leave a reopened layer at pointer-events: none; this one covers the screen, so it is always on top.
          style={{ pointerEvents: 'auto' }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            returnFocus.current?.focus();
          }}
          className={cn('fixed inset-0 z-50 flex items-center justify-center', FADE)}
        >
          {item && (
            <>
              <DialogTitle className="sr-only">{item.name}</DialogTitle>
              <FullSizeMedia key={item.key} item={item} number={index + 1} />
              <div className="absolute right-3 top-3 flex items-center gap-3 sm:right-4 sm:top-4">
                {items.length > 1 && (
                  <span className="font-sans text-[13px] tabular-nums text-background/80">
                    {index + 1} of {items.length}
                  </span>
                )}
                <DialogClose aria-label="Close" className={VIEW_BUTTON}>
                  <X aria-hidden className="h-5 w-5" />
                </DialogClose>
              </div>
              {previous && (
                <button
                  type="button"
                  aria-label="Previous"
                  onClick={() => onOpenKeyChange(previous.key)}
                  className={cn(VIEW_BUTTON, 'absolute left-2 top-1/2 -translate-y-1/2 sm:left-4')}
                >
                  <ChevronLeft aria-hidden className="h-5 w-5" />
                </button>
              )}
              {next && (
                <button
                  type="button"
                  aria-label="Next"
                  onClick={() => onOpenKeyChange(next.key)}
                  className={cn(
                    VIEW_BUTTON,
                    'absolute right-2 top-1/2 -translate-y-1/2 sm:right-4',
                  )}
                >
                  <ChevronRight aria-hidden className="h-5 w-5" />
                </button>
              )}
            </>
          )}
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
}
