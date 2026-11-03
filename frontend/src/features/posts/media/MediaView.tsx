import * as DialogPrimitive from '@radix-ui/react-dialog';
import { ChevronLeft, ChevronRight, Film, Image as ImageIcon, Loader2, X } from 'lucide-react';
import {
  useState,
  type DragEvent,
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
} from 'react';
import {
  Dialog,
  DialogClose,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import type { Media, MediaKind } from '@/services/mediaService';
import { capitalized } from './mediaRules';
import { useFileUrl, useMediaFile, useMediaPreview } from './useMediaPreview';

/** One Media the view can show, as its tile has it. */
export interface Viewable {
  key: string;
  /** As the tile is named, mid-sentence: "image 2", "GIF 1". */
  name: string;
  kind: MediaKind;
  /** Null while it is still uploading. */
  media: Media | null;
  /** The file already in the browser, or a video's first frame, from an upload in this session. */
  localUrl: string | null;
  /** The file picked in this session, if it was. */
  file: File | null;
  /** On a Part already on X, whose files are deleted and only previews kept. */
  onX: boolean;
}

const VIEW_BUTTON =
  'inline-flex h-10 w-10 items-center justify-center rounded-full bg-foreground/75 text-background transition-colors hover:bg-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background motion-reduce:transition-none';

const FADE =
  'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 motion-reduce:!animate-none';

function FullSizeMedia({ item }: { item: Viewable }) {
  // A video's localUrl is only its first frame, so it plays from the picked file instead.
  const localVideo = item.kind === 'video' ? item.file : null;
  const hasLocal = item.kind === 'video' ? localVideo !== null : item.localUrl !== null;
  const fetches = !hasLocal && !item.onX && item.media !== null;
  const localVideoUrl = useFileUrl(localVideo);
  const file = useMediaFile(fetches ? item.media!.id : null);
  const [unplayable, setUnplayable] = useState(false);
  const local = item.kind === 'video' ? localVideoUrl : item.localUrl;
  const full = unplayable ? null : (local ?? file.url);
  const preview = useMediaPreview(full || item.localUrl ? null : (item.media?.previewUrl ?? null));
  const still = item.localUrl ?? preview.url;
  const downloading = fetches && file.url === null && !file.failed;
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
            onError={() => setUnplayable(true)}
            aria-label={capitalized(item.name)}
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
              aria-label={capitalized(item.name)}
              className="flex aspect-video w-[min(90vw,32rem)] items-center justify-center rounded-2xl bg-muted text-muted-foreground"
            >
              <KindIcon aria-hidden className="h-8 w-8" />
            </div>
          )
        )}
        {downloading && item.kind !== 'image' && (
          <div
            role="status"
            aria-label={`Loading ${item.name}`}
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
  fallbackFocus,
}: {
  items: Viewable[];
  /** The key of the Media shown, or null while closed. */
  openKey: string | null;
  onOpenKeyChange: (key: string | null) => void;
  /** The tile the view opened from, focused again once it closes. */
  returnFocus: RefObject<HTMLElement | null>;
  /** Focused instead when that tile is gone, as when its file was refused while open. */
  fallbackFocus: RefObject<HTMLElement | null>;
}) {
  const index = items.findIndex((item) => item.key === openKey);
  const item = index >= 0 ? items[index] : undefined;
  const previous = index > 0 ? items[index - 1] : undefined;
  const next = index >= 0 ? items[index + 1] : undefined;

  const onKeyDown = (event: KeyboardEvent) => {
    // The video's own controls seek with the arrow keys.
    if (event.target instanceof HTMLVideoElement) return;
    const to = event.key === 'ArrowLeft' ? previous : event.key === 'ArrowRight' ? next : undefined;
    if (to) onOpenKeyChange(to.key);
  };

  // A click anywhere but the Media or a control closes it, as one on the backdrop would.
  const onBackgroundClick = (event: MouseEvent) => {
    if (!(event.target as Element).closest('img, video, [role="img"], [role="status"], button'))
      onOpenKeyChange(null);
  };

  // React bubbles events through the portal, so a drop here would reach the Part's drop target
  // behind; left to the browser, it would open the file in place of the page.
  const keepInside = (event: DragEvent) => {
    event.stopPropagation();
    event.preventDefault();
    if (event.type === 'dragover' && event.dataTransfer) event.dataTransfer.dropEffect = 'none';
  };

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
            const opener = returnFocus.current;
            (opener?.isConnected ? opener : fallbackFocus.current)?.focus();
          }}
          className={cn('fixed inset-0 z-50 flex items-center justify-center', FADE)}
        >
          {item && (
            <>
              <DialogTitle className="sr-only">{capitalized(item.name)}</DialogTitle>
              <FullSizeMedia key={item.key} item={item} />
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
