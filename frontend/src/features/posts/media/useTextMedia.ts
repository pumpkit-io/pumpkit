import { useCallback, useEffect, useRef, useState } from 'react';
import { showToast } from '@/components/Toaster';
import { track } from '@/lib/analytics';
import { useConfirmLeaving } from '@/lib/useConfirmLeaving';
import { errorCode } from '@/services/apiErrors';
import { mediaService, type Media } from '@/services/mediaService';
import { postService } from '@/services/postService';
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

const LEAVE_WHILE_UPLOADING =
  "An image is still uploading. If you leave, it won't stay on the post. Leave anyway?";

/**
 * An upload, queued or under way. One under way is never aborted: an abort can't tell whether
 * the server already took the file, so a stopped upload finishes and its Media is taken off.
 */
interface Upload {
  /** Stopped by the User or by leaving the page. */
  dropped: boolean;
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
  const uploads = useRef(new Map<string, Upload>());

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

  const readyTile = useCallback(
    (media: Media): Tile => ({
      key: newKey(),
      state: 'ready',
      media,
      localUrl: null,
      removing: false,
    }),
    [newKey],
  );

  /** Shows the Part's Media as the server holds it, catching any a failed upload left there. */
  const reload = useCallback(
    async (partIndex: number) => {
      let stored: Media[];
      try {
        stored = (await postService.get(postId)).textMedia[partIndex] ?? [];
      } catch {
        return;
      }
      change(partIndex, (tiles) => {
        const ready = new Map(
          tiles.flatMap((t) => (t.state === 'ready' ? [[t.media.id, t] as const] : [])),
        );
        tiles
          .filter((t) => t.state === 'ready' && !stored.some((m) => m.id === t.media.id))
          .forEach(release);
        return [
          ...stored.map((media) => ready.get(media.id) ?? readyTile(media)),
          ...tiles.filter((t) => t.state !== 'ready'),
        ];
      });
    },
    [postId, change, readyTile],
  );

  const upload = useCallback(
    (partIndex: number, key: string, file: File, via: AttachVia) => {
      const under: Upload = { dropped: false };
      uploads.current.set(key, under);
      const run = async () => {
        if (under.dropped) {
          uploads.current.delete(key);
          return;
        }
        try {
          const media = await mediaService.attach(postId, partIndex + 1, file, {
            onProgress: (sent) => {
              changeTile(partIndex, key, (tile) =>
                tile.state === 'uploading' ? { ...tile, progress: sent } : tile,
              );
            },
          });
          if (under.dropped) {
            void mediaService.remove(postId, media.id).catch(() => {});
            return;
          }
          changeTile(partIndex, key, (tile) => ({
            key,
            state: 'ready',
            media,
            localUrl: tile.localUrl,
            removing: false,
          }));
          track('media_attached', { kind: media.kind, via, source: 'web' });
        } catch (error) {
          if (under.dropped) return;
          const refusal = refusalOf(error);
          // A full Part, or a failure that may have come after the server took the file.
          if (refusal.retry || errorCode(error) === 'MEDIA_PART_FULL') void reload(partIndex);
          changeTile(partIndex, key, (tile) => ({
            key,
            state: 'refused',
            file,
            localUrl: tile.localUrl,
            refusal,
            via,
          }));
        } finally {
          uploads.current.delete(key);
        }
      };
      const queued = (queues.current.get(partIndex) ?? Promise.resolve()).then(run);
      queues.current.set(partIndex, queued);
    },
    [postId, changeTile, reload],
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
        const under = uploads.current.get(key);
        if (under) under.dropped = true;
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
  useConfirmLeaving(uploading, LEAVE_WHILE_UPLOADING);

  useEffect(
    () => () => {
      uploads.current.forEach((under) => (under.dropped = true));
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
