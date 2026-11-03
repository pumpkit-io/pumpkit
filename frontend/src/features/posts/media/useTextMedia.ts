import { useCallback, useEffect, useRef, useState } from 'react';
import { showToast } from '@/components/Toaster';
import { track } from '@/lib/analytics';
import { mediaService, type Media } from '@/services/mediaService';
import {
  IMAGES_PER_PART,
  X_MEDIA_RULE,
  refusalBeforeUpload,
  refusalOf,
  type AttachVia,
  type Refusal,
} from './mediaRules';

/** One file on a Part as the card shows it, from the moment it is chosen. */
export type Tile =
  | {
      key: string;
      state: 'uploading';
      file: File;
      /** The chosen file itself, shown until the stored preview loads. */
      localUrl: string | null;
      /** The share sent so far, from 0 to 1. */
      progress: number;
      via: AttachVia;
    }
  | { key: string; state: 'ready'; media: Media; localUrl: string | null; removing: boolean }
  | {
      key: string;
      state: 'refused';
      file: File;
      localUrl: string | null;
      refusal: Refusal;
      via: AttachVia;
    };

export interface TextMedia {
  /** The Part's tiles in order, refused files included. */
  tilesOf: (partIndex: number) => Tile[];
  /** How many more images the Part takes. */
  roomOn: (partIndex: number) => number;
  attach: (partIndex: number, files: File[], via: AttachVia) => void;
  remove: (partIndex: number, key: string) => void;
  retry: (partIndex: number, key: string) => void;
}

/** Whether a tile counts toward what X takes on one X post. */
export function holdsPlace(tile: Tile): boolean {
  return tile.state === 'uploading' || (tile.state === 'ready' && !tile.removing);
}

function localUrlOf(file: File): string | null {
  return typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : null;
}

function release(tile: Tile) {
  if (tile.localUrl && typeof URL.revokeObjectURL === 'function') {
    URL.revokeObjectURL(tile.localUrl);
  }
}

/**
 * The Media on each Part of a Post's Text, kept apart from its words: undo, redo, restoring and
 * Feedback never touch it. Uploads on one Part go one at a time, so the server keeps the order
 * the card shows.
 */
export function useTextMedia(postId: string, initial: Media[][]): TextMedia {
  const nextKey = useRef(0);
  const newKey = useCallback(() => `tile-${++nextKey.current}`, []);
  const [parts, setParts] = useState<Tile[][]>(() =>
    initial.map((onPart) =>
      onPart.map((media) => ({
        key: newKey(),
        state: 'ready' as const,
        media,
        localUrl: null,
        removing: false,
      })),
    ),
  );
  // Read synchronously, so files chosen together each see the room the ones before took.
  const current = useRef(parts);
  const queues = useRef(new Map<number, Promise<void>>());
  const uploads = useRef(new Map<string, AbortController>());

  const change = useCallback((partIndex: number, edit: (tiles: Tile[]) => Tile[]) => {
    const next = [...current.current];
    while (next.length <= partIndex) next.push([]);
    next[partIndex] = edit(next[partIndex] ?? []);
    current.current = next;
    setParts(next);
  }, []);

  const changeTile = useCallback(
    (partIndex: number, key: string, edit: (tile: Tile) => Tile) =>
      change(partIndex, (tiles) => tiles.map((tile) => (tile.key === key ? edit(tile) : tile))),
    [change],
  );

  const upload = useCallback(
    (partIndex: number, key: string, file: File, via: AttachVia) => {
      const controller = new AbortController();
      uploads.current.set(key, controller);
      const run = async () => {
        if (controller.signal.aborted) return;
        try {
          const media = await mediaService.attach(postId, partIndex + 1, file, {
            signal: controller.signal,
            onProgress: (sent) =>
              changeTile(partIndex, key, (tile) =>
                tile.state === 'uploading' ? { ...tile, progress: sent } : tile,
              ),
          });
          changeTile(partIndex, key, (tile) => ({
            key,
            state: 'ready',
            media,
            localUrl: tile.localUrl,
            removing: false,
          }));
          track('media_attached', { kind: media.kind, via, source: 'web' });
        } catch (error) {
          if (controller.signal.aborted) return;
          changeTile(partIndex, key, (tile) => ({
            key,
            state: 'refused',
            file,
            localUrl: tile.localUrl,
            refusal: refusalOf(error),
            via,
          }));
        } finally {
          uploads.current.delete(key);
        }
      };
      const queued = (queues.current.get(partIndex) ?? Promise.resolve()).then(run);
      queues.current.set(partIndex, queued);
    },
    [postId, changeTile],
  );

  const roomOn = useCallback(
    (partIndex: number) =>
      IMAGES_PER_PART - (current.current[partIndex] ?? []).filter(holdsPlace).length,
    [],
  );

  const attach = useCallback(
    (partIndex: number, files: File[], via: AttachVia) => {
      for (const file of files) {
        const key = newKey();
        const localUrl = localUrlOf(file);
        const refusal =
          refusalBeforeUpload(file) ??
          (roomOn(partIndex) > 0 ? null : { message: X_MEDIA_RULE, retry: false });
        if (refusal) {
          change(partIndex, (tiles) => [
            ...tiles,
            { key, state: 'refused', file, localUrl, refusal, via },
          ]);
          continue;
        }
        change(partIndex, (tiles) => [
          ...tiles,
          { key, state: 'uploading', file, localUrl, progress: 0, via },
        ]);
        upload(partIndex, key, file, via);
      }
    },
    [change, newKey, roomOn, upload],
  );

  const retry = useCallback(
    (partIndex: number, key: string) => {
      const tile = current.current[partIndex]?.find((t) => t.key === key);
      if (tile?.state !== 'refused') return;
      if (roomOn(partIndex) <= 0) return;
      changeTile(partIndex, key, () => ({
        key,
        state: 'uploading',
        file: tile.file,
        localUrl: tile.localUrl,
        progress: 0,
        via: tile.via,
      }));
      upload(partIndex, key, tile.file, tile.via);
    },
    [changeTile, roomOn, upload],
  );

  const remove = useCallback(
    (partIndex: number, key: string) => {
      const tile = current.current[partIndex]?.find((t) => t.key === key);
      if (!tile) return;
      const drop = () => {
        release(tile);
        change(partIndex, (tiles) => tiles.filter((t) => t.key !== key));
      };
      if (tile.state !== 'ready') {
        uploads.current.get(key)?.abort();
        drop();
        return;
      }
      changeTile(partIndex, key, (t) => ({ ...t, removing: true }) as Tile);
      mediaService.remove(postId, tile.media.id).then(
        () => {
          drop();
          track('media_removed', { kind: tile.media.kind, source: 'web' });
        },
        () => {
          changeTile(partIndex, key, (t) => ({ ...t, removing: false }) as Tile);
          showToast("Couldn't remove the image. Try again.");
        },
      );
    },
    [postId, change, changeTile],
  );

  const uploading = parts.some((tiles) => tiles.some((tile) => tile.state === 'uploading'));
  useEffect(() => {
    if (!uploading) return;
    const confirmLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older browsers ask only when this is set.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', confirmLeaving);
    return () => window.removeEventListener('beforeunload', confirmLeaving);
  }, [uploading]);

  useEffect(
    () => () => {
      uploads.current.forEach((controller) => controller.abort());
      current.current.flat().forEach(release);
    },
    [],
  );

  return {
    tilesOf: (partIndex) => parts[partIndex] ?? [],
    roomOn,
    attach,
    remove,
    retry,
  };
}
