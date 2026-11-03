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
 * Feedback never touch it. Uploads on one Part, and the read after a failed one, go one at a
 * time, so the server keeps the order the card shows and no read races an upload.
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

  /** Media the page took off the server, which a read racing the removal may still list. */
  const discarded = useRef(new Set<string>());

  const discard = useCallback(
    async (media: Media) => {
      discarded.current.add(media.id);
      await mediaService.remove(postId, media.id).catch(() => {});
    },
    [postId],
  );

  /** The Part's Media as the server holds it, or null when it can't be read. */
  const storedOn = useCallback(
    async (partIndex: number): Promise<Media[] | null> => {
      try {
        const stored = (await postService.get(postId)).textMedia[partIndex] ?? [];
        return stored.filter((media) => !discarded.current.has(media.id));
      } catch {
        return null;
      }
    },
    [postId],
  );

  /** Shows `stored` as the Part's ready tiles, one per Media, keeping the tiles already shown. */
  const show = useCallback(
    (partIndex: number, stored: Media[]) =>
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
      }),
    [change, readyTile],
  );

  /** Turns an upload's tile into its Media's, unless another tile shows that Media already. */
  const settle = useCallback(
    (partIndex: number, key: string, media: Media) =>
      change(partIndex, (tiles) => {
        const shown = tiles.some((t) => t.state === 'ready' && t.media.id === media.id);
        return tiles.flatMap((tile) => {
          if (tile.key !== key) return [tile];
          if (shown) {
            release(tile);
            return [];
          }
          return [
            { key, state: 'ready' as const, media, localUrl: tile.localUrl, removing: false },
          ];
        });
      }),
    [change],
  );

  /**
   * Sends one file, and after a failure reads back the Part's Media. Media the page didn't know
   * of then is this file's, landed before its answer got lost: no other upload runs on the Part.
   */
  const send = useCallback(
    async (partIndex: number, key: string, file: File, via: AttachVia, under: Upload) => {
      let media: Media | null = null;
      let error: unknown = null;
      try {
        media = await mediaService.attach(postId, partIndex + 1, file, {
          onProgress: (sent) => {
            changeTile(partIndex, key, (tile) =>
              tile.state === 'uploading' ? { ...tile, progress: sent } : tile,
            );
          },
        });
      } catch (caught) {
        error = caught;
      }
      const refusal = media ? null : refusalOf(error);
      if (refusal && (refusal.retry || errorCode(error) === 'MEDIA_PART_FULL')) {
        const stored = await storedOn(partIndex);
        if (stored) {
          const known = new Set(
            (current.current[partIndex] ?? []).flatMap((t) =>
              t.state === 'ready' ? [t.media.id] : [],
            ),
          );
          const landed = refusal.retry ? stored.filter((m) => !known.has(m.id)).at(-1) : undefined;
          show(
            partIndex,
            stored.filter((m) => m !== landed),
          );
          media = landed ?? null;
        }
      }
      if (media && under.dropped) {
        await discard(media);
        return;
      }
      if (under.dropped) return;
      if (media) {
        settle(partIndex, key, media);
        track('media_attached', { kind: media.kind, via, source: 'web' });
        return;
      }
      changeTile(partIndex, key, (tile) => ({
        key,
        state: 'refused',
        file,
        localUrl: tile.localUrl,
        refusal: refusal ?? refusalOf(error),
        via,
      }));
    },
    [postId, changeTile, storedOn, show, settle, discard],
  );

  const upload = useCallback(
    (partIndex: number, key: string, file: File, via: AttachVia) => {
      const under: Upload = { dropped: false };
      uploads.current.set(key, under);
      const run = async () => {
        try {
          if (!under.dropped) await send(partIndex, key, file, via, under);
        } finally {
          uploads.current.delete(key);
        }
      };
      const queued = (queues.current.get(partIndex) ?? Promise.resolve()).then(run, run);
      queues.current.set(partIndex, queued);
    },
    [send],
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
          discarded.current.add(tile.media.id);
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
