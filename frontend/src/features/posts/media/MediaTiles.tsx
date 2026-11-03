import { Image as ImageIcon, RotateCw, X } from 'lucide-react';
import type { CSSProperties } from 'react';
import { cn } from '@/lib/utils';
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

function gridStyle(tiles: Tile[]): CSSProperties {
  if (tiles.length > 1) return { aspectRatio: '16 / 9' };
  const tile = tiles[0];
  const media = tile?.state === 'ready' ? tile.media : null;
  const ratio =
    media?.width && media.height
      ? Math.min(SINGLE_RATIO.max, Math.max(SINGLE_RATIO.min, media.width / media.height))
      : SINGLE_RATIO.unknown;
  return { aspectRatio: String(ratio) };
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
  onRemove: () => void;
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
      <button
        type="button"
        aria-label={`Remove image ${number}`}
        onClick={onRemove}
        className={cn(ROUND_BUTTON, 'absolute right-1.5 top-1.5')}
      >
        <X aria-hidden className="h-4 w-4" />
      </button>
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
  onRemove,
  onRetry,
}: {
  tile: Extract<Tile, { state: 'refused' }>;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const name = tile.file.name;
  return (
    <li className="flex items-center gap-3 rounded-xl border border-dashed border-destructive p-2">
      <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted">
        {tile.localUrl && tile.file.type.startsWith('image/') ? (
          <img src={tile.localUrl} alt="" className="h-full w-full object-cover" />
        ) : (
          <ImageIcon aria-hidden className="h-5 w-5 text-muted-foreground" />
        )}
      </div>
      <div className="min-w-0 flex-1 font-sans text-[13px] leading-5">
        <p className="font-medium text-destructive">{tile.refusal.message}</p>
        <p className="truncate text-muted-foreground">{name}</p>
      </div>
      {tile.refusal.retry && (
        <button
          type="button"
          aria-label={`Retry ${name}`}
          onClick={onRetry}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 font-sans text-[13px] font-medium text-foreground transition-colors hover:bg-[var(--hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
        >
          <RotateCw aria-hidden className="h-3.5 w-3.5" />
          Retry
        </button>
      )}
      <button
        type="button"
        aria-label={`Remove ${name}`}
        onClick={onRemove}
        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-[var(--hover)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
      >
        <X aria-hidden className="h-4 w-4" />
      </button>
    </li>
  );
}

/**
 * A Part's Media under its text, in X's layout for one to four images, then any file that
 * couldn't go on it, with why. `where` names the Part: "Part 2", or "the post".
 */
export function MediaTiles({
  tiles,
  where,
  onRemove,
  onRetry,
}: {
  tiles: Tile[];
  where: string;
  onRemove: (key: string) => void;
  onRetry: (key: string) => void;
}) {
  const placed = tiles.filter(holdsPlace);
  const refused = tiles.filter(
    (t): t is Extract<Tile, { state: 'refused' }> => t.state === 'refused',
  );
  if (!placed.length && !refused.length) return null;
  const cells = CELLS[placed.length] ?? CELLS[4]!;
  return (
    <div className="space-y-2">
      {placed.length > 0 && (
        <ul
          aria-label={`Media on ${where}`}
          style={gridStyle(placed)}
          className={cn(
            'grid max-h-[32rem] w-full gap-0.5 overflow-hidden rounded-2xl border border-border bg-card',
            placed.length > 1 && 'grid-cols-2',
            placed.length > 2 && 'grid-rows-2',
          )}
        >
          {placed.map((tile, index) => (
            <MediaTile
              key={tile.key}
              tile={tile}
              number={index + 1}
              className={cells[index] ?? ''}
              onRemove={() => onRemove(tile.key)}
            />
          ))}
        </ul>
      )}
      {refused.length > 0 && (
        <ul aria-label={`Refused media on ${where}`} className="space-y-2">
          {refused.map((tile) => (
            <RefusedTile
              key={tile.key}
              tile={tile}
              onRemove={() => onRemove(tile.key)}
              onRetry={() => onRetry(tile.key)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
