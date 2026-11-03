import {
  Film,
  Image as ImageIcon,
  LoaderCircle,
  Play,
  RotateCw,
  TriangleAlert,
  X,
} from 'lucide-react';
import { useContext, useRef, useState, type CSSProperties } from 'react';
import { XConnectionContext } from '@/features/xConnection/XConnectionProvider';
import { cn } from '@/lib/utils';
import type { Media } from '@/services/mediaService';
import { AltTextChip, AltTextMark, CHIP, SOLID } from './AltText';
import {
  breaksXMediaRule,
  capitalized,
  formatDuration,
  LONG_VIDEO,
  mediaNoun,
  PREMIUM_VIDEO_MS,
  X_MEDIA_RULE,
} from './mediaRules';
import { MediaView, type Viewable } from './MediaView';
import { useMediaPreview } from './useMediaPreview';
import { holdsPlace, kindOfTile, type Tile } from './useTextMedia';

// X's composer shows one Media full width at its own shape, cropped from the centre past 3:4 tall.
// However wide, its frame stays tall enough for the × and the Alt chip, cropping a wider banner.
const SINGLE_RATIO = { min: 3 / 4, unknown: 16 / 9 };
const SINGLE_MIN_HEIGHT = '5rem';

/** Where each of two, three or four tiles sits in the 16:9 frame of X's composer. */
const CELLS: Record<number, CSSProperties[]> = {
  2: [
    { gridColumn: '1', gridRow: '1' },
    { gridColumn: '2', gridRow: '1' },
  ],
  3: [
    { gridColumn: '1', gridRow: '1 / span 2' },
    { gridColumn: '2', gridRow: '1' },
    { gridColumn: '2', gridRow: '2' },
  ],
  4: [
    { gridColumn: '1', gridRow: '1' },
    { gridColumn: '2', gridRow: '1' },
    { gridColumn: '1', gridRow: '2' },
    { gridColumn: '2', gridRow: '2' },
  ],
};

/** Each tile's width over its height, by key, as the browser read it from the file shown. */
type Ratios = Record<string, number>;

function useMeasured() {
  const [measured, setMeasured] = useState<Ratios>({});
  const measure = (key: string) => (ratio: number) =>
    setMeasured((ratios) => (ratios[key] === ratio ? ratios : { ...ratios, [key]: ratio }));
  return { measured, measure };
}

function gridStyle(tiles: Tile[], measured: Ratios = {}): CSSProperties | undefined {
  if (tiles.length > 4) return undefined;
  if (tiles.length > 1) return { aspectRatio: '16 / 9' };
  const tile = tiles[0]!;
  const media = tile.state === 'ready' ? tile.media : null;
  const ratio = media?.width && media.height ? media.width / media.height : measured[tile.key];
  return {
    aspectRatio: String(ratio ? Math.max(SINGLE_RATIO.min, ratio) : SINGLE_RATIO.unknown),
    minHeight: SINGLE_MIN_HEIGHT,
  };
}

function gridClass(tiles: Tile[]): string {
  if (tiles.length > 4) {
    return 'grid w-full grid-cols-2 gap-0.5 overflow-hidden rounded-2xl border border-border bg-card';
  }
  return cn(
    'grid w-full gap-3',
    tiles.length > 1 && 'grid-cols-2',
    tiles.length > 2 && 'grid-rows-2',
  );
}

function tileLayout(count: number, index: number): { className: string; style?: CSSProperties } {
  if (count > 4) return { className: 'aspect-video' };
  return { className: 'rounded-2xl', style: CELLS[count]?.[index] };
}

const ROUND_BUTTON =
  'inline-flex h-7 w-7 items-center justify-center rounded-full bg-foreground/75 text-background transition-colors hover:bg-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card motion-reduce:transition-none';

/** The tiles, refused files already left out, as the full-size view shows them. */
function viewablesOf(tiles: Tile[], onX: boolean): Viewable[] {
  return tiles.map((tile, index) => {
    const kind = kindOfTile(tile);
    return {
      key: tile.key,
      name: `${mediaNoun(kind)} ${index + 1}`,
      kind,
      media: tile.state === 'ready' ? tile.media : null,
      localUrl: tile.localUrl,
      file: tile.file,
      onX,
    };
  });
}

/** The full-size view of a Part's Media, how a tile opens it, and the list it falls back to. */
function useMediaView(items: Viewable[]) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const list = useRef<HTMLUListElement | null>(null);
  const open = (key: string) => (element: HTMLElement) => {
    opener.current = element;
    setOpenKey(key);
  };
  const nameOf = (key: string) => items.find((item) => item.key === key)!.name;
  const view = (
    <MediaView
      items={items}
      openKey={openKey}
      onOpenKeyChange={setOpenKey}
      returnFocus={opener}
      fallbackFocus={list}
    />
  );
  return { open, view, list, nameOf };
}

const LIST_FOCUS = 'focus-visible:outline-none';

/** A video's length as the browser read it, on its tile or its stored Media. */
function durationOf(tile: Tile): number | null {
  return tile.state === 'ready' ? tile.media.durationMs : tile.durationMs;
}

function MediaTile({
  tile,
  name,
  className,
  style,
  onMeasure,
  onOpen,
  onRemove,
  onDescribe,
}: {
  tile: Tile;
  /** Mid-sentence: "image 2". */
  name: string;
  className: string;
  style?: CSSProperties;
  /** Called with the width over the height of the file shown, once the browser reads it. */
  onMeasure?: (ratio: number) => void;
  /** Opens the tile full size; given the element to focus again once that closes. */
  onOpen: (opener: HTMLElement) => void;
  /** Left out, the tile can't be removed: the Part is set to go, or went, to X. */
  onRemove?: () => void;
  /** Left out, its alt text can't change either. */
  onDescribe?: (altText: string | null) => Promise<void>;
}) {
  const media = tile.state === 'ready' ? tile.media : null;
  const kind = kindOfTile(tile);
  const preview = useMediaPreview(media?.previewUrl ?? null);
  const describable = media !== null && kind !== 'video';
  const src = preview.url ?? tile.localUrl;
  const progress = tile.state === 'uploading' ? Math.round(tile.progress * 100) : null;
  const duration = durationOf(tile);
  const KindIcon = kind === 'video' ? Film : ImageIcon;
  const reading = tile.state === 'uploading' && tile.reading;
  return (
    <li
      aria-label={capitalized(name)}
      style={style}
      className={cn('relative overflow-hidden bg-muted', className)}
    >
      {reading ? (
        <div
          role="status"
          className="absolute inset-0 flex items-center justify-center text-muted-foreground"
        >
          <LoaderCircle aria-hidden className="h-6 w-6 animate-spin motion-reduce:animate-none" />
          <span className="sr-only">Reading {name}</span>
        </div>
      ) : src ? (
        <img
          src={src}
          alt={media?.altText ?? ''}
          onLoad={({ currentTarget: { naturalWidth, naturalHeight } }) => {
            if (naturalWidth && naturalHeight) onMeasure?.(naturalWidth / naturalHeight);
          }}
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        (preview.failed || !media?.previewUrl) && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <KindIcon aria-hidden className="h-6 w-6" />
            {preview.failed && <span className="sr-only">Preview didn&apos;t load</span>}
          </div>
        )
      )}
      <button
        type="button"
        aria-label={`Open ${name}`}
        onClick={(event) => onOpen(event.currentTarget)}
        className="absolute inset-0 cursor-pointer rounded-[inherit] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      />
      <div className="absolute bottom-1.5 left-1.5 flex items-center gap-1">
        {kind === 'gif' && (
          <span aria-hidden className={cn(CHIP, SOLID)}>
            GIF
          </span>
        )}
        {kind === 'video' && (
          <span className={cn(CHIP, SOLID, 'gap-1 tabular-nums')}>
            <Play aria-hidden className="h-3 w-3 fill-current" />
            {duration !== null && (
              <>
                <span className="sr-only">Length </span>
                {formatDuration(duration)}
              </>
            )}
          </span>
        )}
        {describable &&
          (onDescribe ? (
            <AltTextChip media={media} name={name} onSave={onDescribe} />
          ) : (
            <AltTextMark media={media} />
          ))}
      </div>
      {onRemove && (
        <button
          type="button"
          aria-label={`Remove ${name}`}
          onClick={onRemove}
          className={cn(ROUND_BUTTON, 'absolute right-1.5 top-1.5')}
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      )}
      {progress !== null && (
        <div
          role="progressbar"
          aria-label={`Uploading ${name}`}
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
  style,
  canRetry,
  onRemove,
  onRetry,
}: {
  tile: Extract<Tile, { state: 'refused' }>;
  className: string;
  style?: CSSProperties;
  canRetry: boolean;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const name = tile.file.name;
  return (
    <li
      aria-label={name}
      style={style}
      className={cn('relative overflow-hidden bg-muted', className)}
    >
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

/** Under a video X would refuse: over 20 minutes, on a connected X account without Premium. */
function LongVideoWarning({ tiles }: { tiles: Tile[] }) {
  const connection = useContext(XConnectionContext)?.connection;
  const long = tiles.some(
    (tile) =>
      holdsPlace(tile) &&
      kindOfTile(tile) === 'video' &&
      (durationOf(tile) ?? 0) > PREMIUM_VIDEO_MS,
  );
  if (!long || !connection || connection.premium) return null;
  return (
    <p className="flex items-start gap-1.5 font-sans text-[13px] font-medium text-foreground">
      <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
      {LONG_VIDEO}
    </p>
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
  onDescribe,
}: {
  tiles: Tile[];
  where: string;
  canRetry: boolean;
  onRemove: (key: string) => void;
  onRetry: (key: string) => void;
  onDescribe: (key: string, altText: string | null) => Promise<void>;
}) {
  const { measured, measure } = useMeasured();
  const shown = tiles.filter((t) => holdsPlace(t) || t.state === 'refused');
  const { open, view, list, nameOf } = useMediaView(
    viewablesOf(
      shown.filter((t) => t.state !== 'refused'),
      false,
    ),
  );
  if (!shown.length) return null;
  const media = shown.flatMap((t) => (t.state === 'ready' && !t.removing ? [t.media] : []));
  const grid = (
    <ul
      ref={list}
      tabIndex={-1}
      aria-label={`Media on ${where}`}
      style={gridStyle(shown, measured)}
      className={cn(gridClass(shown), LIST_FOCUS)}
    >
      {shown.map((tile, index) => {
        const layout = tileLayout(shown.length, index);
        return tile.state === 'refused' ? (
          <RefusedTile
            key={tile.key}
            tile={tile}
            {...layout}
            canRetry={canRetry}
            onRemove={() => onRemove(tile.key)}
            onRetry={() => onRetry(tile.key)}
          />
        ) : (
          <MediaTile
            key={tile.key}
            tile={tile}
            name={nameOf(tile.key)}
            {...layout}
            onMeasure={measure(tile.key)}
            onOpen={open(tile.key)}
            onRemove={() => onRemove(tile.key)}
            onDescribe={(altText) => onDescribe(tile.key, altText)}
          />
        );
      })}
    </ul>
  );
  return (
    <div className="space-y-1.5">
      {grid}
      {view}
      {breaksXMediaRule(media) && (
        <p className="font-sans text-[13px] font-medium text-destructive">
          {X_MEDIA_RULE}. Remove some media from {where} before posting.
        </p>
      )}
      <LongVideoWarning tiles={shown} />
    </div>
  );
}

/**
 * Media that can't change any more, such as a Scheduled post's, in the same layout. `onX` marks
 * a Part already on X, which shows only previews.
 */
export function ReadOnlyMediaTiles({
  media,
  where,
  onX = false,
}: {
  media: Media[];
  where: string;
  onX?: boolean;
}) {
  const { measured, measure } = useMeasured();
  const shown = media.map((m): Tile => ({
    key: m.id,
    state: 'ready',
    media: m,
    localUrl: null,
    file: null,
    removing: false,
  }));
  const { open, view, list, nameOf } = useMediaView(viewablesOf(shown, onX));
  if (!shown.length) return null;
  return (
    <>
      <ul
        ref={list}
        tabIndex={-1}
        aria-label={`Media on ${where}`}
        style={gridStyle(shown, measured)}
        className={cn(gridClass(shown), LIST_FOCUS)}
      >
        {shown.map((tile, index) => (
          <MediaTile
            key={tile.key}
            tile={tile}
            name={nameOf(tile.key)}
            {...tileLayout(shown.length, index)}
            onMeasure={measure(tile.key)}
            onOpen={open(tile.key)}
          />
        ))}
      </ul>
      {view}
    </>
  );
}
