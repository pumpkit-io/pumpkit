import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { showToast } from '@/components/Toaster';
import { track } from '@/lib/analytics';
import { useConfirmLeaving } from '@/lib/useConfirmLeaving';
import { errorCode, errorStatus } from '@/services/apiErrors';
import type { Media } from '@/services/mediaService';
import {
  IMAGES_PER_PART,
  X_MEDIA_RULE,
  refusalBeforeUpload,
  refusalOf,
  type AttachVia,
  type Refusal,
} from './mediaRules';
import { textMediaPlace, type MediaPlace } from './mediaPlaces';

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
  remove: (key: string) => void;
  retry: (key: string) => void;
}

/** Whether a tile counts toward what X takes on one X post. */
export function holdsPlace(tile: Tile): boolean {
  return tile.state === 'uploading' || (tile.state === 'ready' && !tile.removing);
}

function localUrlOf(file: File): string | null {
  return typeof URL.createObjectURL === 'function' ? URL.createObjectURL(file) : null;
}

const RECONNECT_FOR_MEDIA = 'X_RECONNECT_FOR_MEDIA';

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
 * The Media on each Part of a Post's Text, apart from its words. Uploads on one Part, and the
 * read after a failed one, go one at a time, so the server keeps the order the card shows.
 */
export function useTextMedia(
  postId: string,
  initial: Media[][],
  /** How many Parts the server's Text has. */
  partCount: number,
  /** Called when the server refuses an upload until X is reconnected; the file is dropped. */
  onReconnectNeeded: () => void,
  /** Where the Media lives instead of the Text, such as a Scheduled post's own copy. */
  placeInstead?: MediaPlace,
): TextMedia {
  const place = useMemo(() => placeInstead ?? textMediaPlace(postId), [placeInstead, postId]);
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

  /** The Part a tile is on now, which a rewrite may have moved it to since it was chosen. */
  const partWith = useCallback(
    (key: string) => current.current.findIndex((tiles) => tiles.some((t) => t.key === key)),
    [],
  );

  /** Edits the tiles of the Part that holds `key`, if any still does. */
  const changePartWith = useCallback(
    (key: string, edit: (tiles: Tile[]) => Tile[]) => {
      const on = partWith(key);
      if (on !== -1) change(on, edit);
    },
    [change, partWith],
  );

  const changeTile = useCallback(
    (key: string, edit: (tile: Tile) => Tile) =>
      changePartWith(key, (tiles) => tiles.map((tile) => (tile.key === key ? edit(tile) : tile))),
    [changePartWith],
  );

  const dropTile = useCallback(
    (key: string) =>
      changePartWith(key, (tiles) =>
        tiles.filter((tile) => {
          if (tile.key === key) release(tile);
          return tile.key !== key;
        }),
      ),
    [changePartWith],
  );

  // Moves tiles once the server has moved their Media: posts/media.move_dropped_parts_media.
  useLayoutEffect(() => {
    if (current.current.length <= partCount) return;
    const last = partCount - 1;
    current.current = [...current.current.slice(0, last), current.current.slice(last).flat()];
    setParts(current.current);
  }, [partCount]);

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
      await place.remove(media.id).catch(() => {});
    },
    [place],
  );

  /** The Part's Media as the server holds it, or null when it can't be read. */
  const storedOn = useCallback(
    async (partIndex: number): Promise<Media[] | null> => {
      try {
        const stored = (await place.read())[partIndex] ?? [];
        return stored.filter((media) => !discarded.current.has(media.id));
      } catch {
        return null;
      }
    },
    [place],
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
    (key: string, media: Media) =>
      changePartWith(key, (tiles) => {
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
    [changePartWith],
  );

  /**
   * Sends one file to the Part its tile is on, and after a failure reads back that Part's Media.
   * Media the page didn't know of then is this file's, landed before its answer got lost.
   */
  const send = useCallback(
    async (key: string, file: File, via: AttachVia, under: Upload) => {
      const sentTo = partWith(key);
      if (sentTo === -1) return;
      let media: Media | null = null;
      let error: unknown = null;
      try {
        media = await place.attach(sentTo + 1, file, {
          onProgress: (sent) => {
            changeTile(key, (tile) =>
              tile.state === 'uploading' ? { ...tile, progress: sent } : tile,
            );
          },
        });
      } catch (caught) {
        error = caught;
      }
      if (errorCode(error) === RECONNECT_FOR_MEDIA) {
        if (under.dropped) return;
        dropTile(key);
        onReconnectNeeded();
        return;
      }
      // A dropped upload's tile is gone, so its Part is the one it went to.
      const on = under.dropped ? sentTo : partWith(key);
      // A rewrite dropped the Part while the file went to it, so the server refused it.
      const partGone = on !== sentTo && errorStatus(error) === 404;
      const refusal = media ? null : refusalOf(partGone ? null : error);
      if (refusal && (refusal.retry || errorCode(error) === 'MEDIA_PART_FULL')) {
        const stored = await storedOn(on);
        if (stored) {
          const known = new Set(
            (current.current[on] ?? []).flatMap((t) => (t.state === 'ready' ? [t.media.id] : [])),
          );
          const landed = refusal.retry ? stored.filter((m) => !known.has(m.id)).at(-1) : undefined;
          if (!under.dropped) {
            show(
              on,
              stored.filter((m) => m !== landed),
            );
          }
          media = landed ?? null;
        }
      }
      if (media && under.dropped) {
        await discard(media);
        return;
      }
      if (under.dropped) return;
      if (media) {
        settle(key, media);
        track('media_attached', { kind: media.kind, via, source: 'web' });
        return;
      }
      changeTile(key, (tile) => ({
        key,
        state: 'refused',
        file,
        localUrl: tile.localUrl,
        refusal: refusal ?? refusalOf(error),
        via,
      }));
    },
    [place, partWith, changeTile, dropTile, storedOn, show, settle, discard, onReconnectNeeded],
  );

  const upload = useCallback(
    (partIndex: number, key: string, file: File, via: AttachVia) => {
      const under: Upload = { dropped: false };
      uploads.current.set(key, under);
      const run = async () => {
        try {
          if (!under.dropped) await send(key, file, via, under);
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
    (key: string) => {
      const on = partWith(key);
      const tile = current.current[on]?.find((t) => t.key === key);
      if (tile?.state !== 'refused') return;
      if (roomOn(on) <= 0) return;
      changeTile(key, () => ({
        key,
        state: 'uploading',
        file: tile.file,
        localUrl: tile.localUrl,
        progress: 0,
        via: tile.via,
      }));
      upload(on, key, tile.file, tile.via);
    },
    [partWith, changeTile, roomOn, upload],
  );

  const remove = useCallback(
    (key: string) => {
      const tile = current.current[partWith(key)]?.find((t) => t.key === key);
      if (!tile) return;
      if (tile.state !== 'ready') {
        const under = uploads.current.get(key);
        if (under) under.dropped = true;
        dropTile(key);
        return;
      }
      changeTile(key, (t) => ({ ...t, removing: true }) as Tile);
      place.remove(tile.media.id).then(
        () => {
          discarded.current.add(tile.media.id);
          dropTile(key);
          track('media_removed', { kind: tile.media.kind, source: 'web' });
        },
        () => {
          changeTile(key, (t) => ({ ...t, removing: false }) as Tile);
          showToast("Couldn't remove the image. Try again.");
        },
      );
    },
    [place, partWith, changeTile, dropTile],
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
