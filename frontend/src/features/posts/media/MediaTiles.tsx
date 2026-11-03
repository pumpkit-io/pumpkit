import { Image as ImageIcon, RotateCw, X } from 'lucide-react';
import type { CSSProperties } from 'react';
import { cn } from '@/lib/utils';
import type { Media } from '@/services/mediaService';
import { breaksXMediaRule, X_MEDIA_RULE } from './mediaRules';
import { useMediaPreview } from './useMediaPreview';
import { holdsPlace, type Tile } from './useTextMedia';

/** X shows one image at about its own shape, within these bounds, and crops the rest. */
const SINGLE_RATIO = { min: 0.8, max: 1.91, unknown: 16 / 9 };

/** Where each of n tiles sits in X's layout for one, two, three or four images. */
const CELLS: Record<number, string[]> = {
  1: [''],
  2: ['', ''],
  3: ['row-span-2', '', ''],
  4: ['', '', '', ''],
};

function gridStyle(tiles: Tile[]): CSSProperties | undefined {
  if (tiles.length > 4) return undefined;
  if (tiles.length > 1) return { aspectRatio: '16 / 9' };
  const tile = tiles[0];
  const media = tile?.state === 'ready' ? tile.media : null;
  const ratio =
    media?.width && media.height
      ? Math.min(SINGLE_RATIO.max, Math.max(SINGLE_RATIO.min, media.width / media.height))
      : SINGLE_RATIO.unknown;
  return { aspectRatio: String(ratio) };
}

function gridClass(tiles: Tile[]): string {
  const many = tiles.length > 4;
  return cn(
    'grid w-full gap-0.5 overflow-hidden rounded-2xl border border-border bg-card',
    !many && 'max-h-[32rem]',
    tiles.length > 1 && 'grid-cols-2',
    tiles.length > 2 && !many && 'grid-rows-2',
  );
}

const ROUND_BUTTON =
  'inline-flex h-7 w-7 items-center justify-center rounded-full bg-foreground/75 text-background transition-colors hover:bg-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card motion-reduce:transition-none';

function MediaTile({
  tile,
  number,
  className,
  onRemove,
}: {
  tile: Tile;
  number: number;
  className: string;
  /** Left out, the tile can't be removed: the Part is set to go, or went, to X. */
  onRemove?: () => void;
}) {
  const preview = useMediaPreview(tile.state === 'ready' ? tile.media.previewUrl : null);
  const src = preview.url ?? tile.localUrl;
  const progress = tile.state === 'uploading' ? Math.round(tile.progress * 100) : null;
  return (
    <li
      aria-label={`Image ${number}`}
      className={cn('relative overflow-hidden bg-muted', className)}
    >
      {src ? (
        <img src={src} alt="" className="absolute inset-0 h-full w-full object-cover" />
      ) : (
        preview.failed && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <ImageIcon aria-hidden className="h-6 w-6" />
            <span className="sr-only">Preview didn&apos;t load</span>
          </div>
        )
      )}
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove image ${number}`}
          onClick={onRemove}
          className={cn(ROUND_BUTTON, 'absolute right-1.5 top-1.5')}
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      )}
      {progress !== null && (
        <div
          role="progressbar"
          aria-label={`Uploading image ${number}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          className="absolute inset-x-0 bottom-0 h-1 bg-foreground/15"
        >
          <div
            className="h-full bg-primary transition-[width] motion-reduce:transition-none"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </li>
  );
}

function RefusedTile({
  tile,
  className,
  canRetry,
  onRemove,
  onRetry,
}: {
  tile: Extract<Tile, { state: 'refused' }>;
  className: string;
  canRetry: boolean;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const name = tile.file.name;
  return (
    <li aria-label={name} className={cn('relative overflow-hidden bg-muted', className)}>
      {tile.localUrl && tile.file.type.startsWith('image/') && (
        <img
          src={tile.localUrl}
          alt=""
          className="absolute inset-0 h-full w-full object-cover opacity-20"
        />
      )}
      <div className="absolute inset-1 flex flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-destructive px-2 pt-6 text-center font-sans text-xs leading-4 sm:px-8 sm:pt-0 sm:text-[13px] sm:leading-5">
        <p className="font-medium text-destructive">{tile.refusal.message}</p>
        <p className="hidden max-w-full truncate text-muted-foreground sm:block">{name}</p>
        {canRetry && tile.refusal.retry && (
          <button
            type="button"
            aria-label={`Retry ${name}`}
            onClick={onRetry}
            className={cn(
              ROUND_BUTTON,
              // A corner button like the × on narrow tiles, a labelled one under the cause on wider ones.
              'absolute left-0.5 top-0.5 gap-1.5 sm:static sm:mt-1 sm:h-8 sm:w-auto sm:rounded-lg sm:bg-card sm:px-2.5 sm:font-medium sm:text-foreground sm:hover:bg-[var(--hover)]',
            )}
          >
            <RotateCw aria-hidden className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Retry</span>
          </button>
        )}
      </div>
      <button
        type="button"
        aria-label={`Remove ${name}`}
        onClick={onRemove}
        className={cn(ROUND_BUTTON, 'absolute right-1.5 top-1.5')}
      >
        <X aria-hidden className="h-4 w-4" />
      </button>
    </li>
  );
}

/**
 * A Part's Media in X's layout, refused files among them with why; `where` names the Part.
 * A rewrite with fewer Parts can leave more Media than X takes: all show, with the rule under.
 */
export function MediaTiles({
  tiles,
  where,
  canRetry,
  onRemove,
  onRetry,
}: {
  tiles: Tile[];
  where: string;
  canRetry: boolean;
  onRemove: (key: string) => void;
  onRetry: (key: string) => void;
}) {
  const shown = tiles.filter((t) => holdsPlace(t) || t.state === 'refused');
  if (!shown.length) return null;
  const many = shown.length > 4;
  const cells = CELLS[shown.length] ?? [];
  const media = shown.flatMap((t) => (t.state === 'ready' && !t.removing ? [t.media] : []));
  let images = 0;
  const grid = (
    <ul aria-label={`Media on ${where}`} style={gridStyle(shown)} className={gridClass(shown)}>
      {shown.map((tile, index) => {
        const className = many ? 'aspect-video' : (cells[index] ?? '');
        return tile.state === 'refused' ? (
          <RefusedTile
            key={tile.key}
            tile={tile}
            className={className}
            canRetry={canRetry}
            onRemove={() => onRemove(tile.key)}
            onRetry={() => onRetry(tile.key)}
          />
        ) : (
          <MediaTile
            key={tile.key}
            tile={tile}
            number={++images}
            className={className}
            onRemove={() => onRemove(tile.key)}
          />
        );
      })}
    </ul>
  );
  if (!breaksXMediaRule(media)) return grid;
  return (
    <div className="space-y-1.5">
      {grid}
      <p className="font-sans text-[13px] font-medium text-destructive">
        {X_MEDIA_RULE}. Remove some media from {where} before posting.
      </p>
    </div>
  );
}

/** Media that can't change any more, such as a Scheduled post's, in the same layout. */
export function ReadOnlyMediaTiles({ media, where }: { media: Media[]; where: string }) {
  const shown = media.map((m): Tile => ({
    key: m.id,
    state: 'ready',
    media: m,
    localUrl: null,
    removing: false,
  }));
  if (!shown.length) return null;
  const cells = CELLS[shown.length] ?? [];
  return (
    <ul aria-label={`Media on ${where}`} style={gridStyle(shown)} className={gridClass(shown)}>
      {shown.map((tile, index) => (
        <MediaTile
          key={tile.key}
          tile={tile}
          number={index + 1}
          className={shown.length > 4 ? 'aspect-video' : (cells[index] ?? '')}
        />
      ))}
    </ul>
  );
}
