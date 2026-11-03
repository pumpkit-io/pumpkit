import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { showToast } from '@/components/Toaster';
import { track } from '@/lib/analytics';
import { useConfirmLeaving } from '@/lib/useConfirmLeaving';
import { errorCode, errorStatus } from '@/services/apiErrors';
import { mediaService, type Media } from '@/services/mediaService';
import { postService } from '@/services/postService';
import {
  IMAGES_PER_PART,
  UPLOAD_FAILED,
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

function readyTile(
  key: string,
  media: Media,
  localUrl: string | null,
): Extract<Tile, { state: 'ready' }> {
  return { key, state: 'ready', media, localUrl, removing: false };
}

/** `parts` with every Part from `count` on appended to the last one, as the server moves Media. */
function folded<T>(parts: T[][], count: number): T[][] {
  if (count < 1 || parts.length <= count) return parts;
  return [...parts.slice(0, count - 1), parts.slice(count - 1).flat()];
}

/**
 * The Media on each Part of a Post's Text, apart from its words. Uploads and removals share one
 * queue for the whole Text, so a read after a failed upload sees nothing else under way.
 */
export function useTextMedia(
  postId: string,
  initial: Media[][],
  /** How many Parts the server's Text has. */
  partCount: number,
  /** Called when the server refuses an upload until X is reconnected; the file is dropped. */
  onReconnectNeeded: () => void,
): TextMedia {
  const nextKey = useRef(0);
  const newKey = useCallback(() => `tile-${++nextKey.current}`, []);
  const [parts, setParts] = useState<Tile[][]>(() =>
    initial.map((onPart) => onPart.map((media) => readyTile(newKey(), media, null))),
  );
  // Read synchronously, so files chosen together each see the room the ones before took.
  const current = useRef(parts);
  /** The Parts a read found the server's Text to have, under the `partCount` then given. */
  const stored = useRef({ partCount, count: partCount });
  const latestPartCount = useRef(partCount);
  /** Counts `partCount` changes, so a read can tell the Text changed while it was under way. */
  const partCountChanges = useRef(0);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const uploads = useRef(new Map<string, Upload>());
  /** Media the page took off the server, which a later read may still list. */
  const discarded = useRef(new Set<string>());

  const set = useCallback((next: Tile[][]) => {
    current.current = next;
    setParts(next);
  }, []);

  /** Whether the Part is on the server yet; one an undo shows before it lands isn't. */
  const isStored = useCallback(
    (partIndex: number) =>
      partIndex < (stored.current.partCount === partCount ? stored.current.count : partCount),
    [partCount],
  );

  const change = useCallback(
    (partIndex: number, edit: (tiles: Tile[]) => Tile[]) => {
      const next = [...current.current];
      while (next.length <= partIndex) next.push([]);
      next[partIndex] = edit(next[partIndex] ?? []);
      set(next);
    },
    [set],
  );

  const partWith = useCallback(
    (key: string) => current.current.findIndex((tiles) => tiles.some((t) => t.key === key)),
    [],
  );

  const tileWith = useCallback(
    (key: string) => current.current.flat().find((t) => t.key === key),
    [],
  );

  const changeTile = useCallback(
    (key: string, edit: (tile: Tile) => Tile) =>
      set(current.current.map((tiles) => tiles.map((t) => (t.key === key ? edit(t) : t)))),
    [set],
  );

  const dropTile = useCallback(
    (key: string) =>
      set(
        current.current.map((tiles) =>
          tiles.filter((t) => {
            if (t.key === key) release(t);
            return t.key !== key;
          }),
        ),
      ),
    [set],
  );

  // Moves tiles once the server has moved their Media: posts/media.move_dropped_parts_media.
  useLayoutEffect(() => {
    latestPartCount.current = partCount;
    partCountChanges.current++;
    if (current.current.length > partCount) set(folded(current.current, partCount));
  }, [partCount, set]);

  const discard = useCallback(
    async (media: Media) => {
      discarded.current.add(media.id);
      await mediaService.remove(postId, media.id).catch(() => {});
    },
    [postId],
  );

  /**
   * The Media on each Part of the server's Text, or null when it can't be read. Never more Parts
   * than `partCount`, and exactly that many when the Text changed while the read was under way.
   */
  const read = useCallback(async (): Promise<Media[][] | null> => {
    const changesBefore = partCountChanges.current;
    let text: Media[][];
    try {
      text = (await postService.get(postId)).textMedia;
    } catch {
      return null;
    }
    if (text.length === 0) return null;
    const count =
      changesBefore === partCountChanges.current
        ? Math.min(text.length, latestPartCount.current)
        : latestPartCount.current;
    const server = folded(
      text.map((onPart) => onPart.filter((m) => !discarded.current.has(m.id))),
      count,
    );
    while (server.length < count) server.push([]);
    return server;
  }, [postId]);

  /**
   * Shows each Part's Media as the server holds it, matching tiles by Media id, with the files
   * not yet stored after them. `claimed` turns the tile `key` into that Media's tile.
   */
  const reconcile = useCallback(
    (server: Media[][], claimed: { key: string; media: Media } | null) => {
      stored.current = { partCount: latestPartCount.current, count: server.length };
      const tiles = current.current.flat();
      const shown = new Map(
        tiles.flatMap((t) => (t.state === 'ready' ? [[t.media.id, t] as const] : [])),
      );
      const claimedTile = claimed ? tiles.find((t) => t.key === claimed.key) : undefined;
      if (claimed && claimedTile) {
        shown.set(claimed.media.id, readyTile(claimed.key, claimed.media, claimedTile.localUrl));
      }
      const onServer = new Set(server.flat().map((m) => m.id));
      tiles.filter((t) => t.state === 'ready' && !onServer.has(t.media.id)).forEach(release);
      const pending = folded(current.current, server.length).map((onPart) =>
        onPart.filter((t) => t.state !== 'ready' && t.key !== claimed?.key),
      );
      set(
        server.map((onPart, index) => [
          ...onPart.map((media) => shown.get(media.id) ?? readyTile(newKey(), media, null)),
          ...(pending[index] ?? []),
        ]),
      );
    },
    [newKey, set],
  );

  const enqueue = useCallback((job: () => Promise<void>) => {
    queue.current = queue.current.then(job, job);
  }, []);

  /**
   * Sends one file to the Part its tile is on. After a failure it reads the whole Text's Media:
   * one Media the page didn't know of then is this file's, landed before its answer got lost.
   */
  const send = useCallback(
    async (key: string, file: File, via: AttachVia, under: Upload) => {
      for (let attempt = 0; ; attempt++) {
        const sentTo = partWith(key);
        if (sentTo === -1) return;
        let media: Media | null = null;
        let error: unknown = null;
        try {
          media = await mediaService.attach(postId, sentTo + 1, file, {
            onProgress: (sent) => {
              changeTile(key, (tile) =>
                tile.state === 'uploading' ? { ...tile, progress: sent } : tile,
              );
            },
          });
        } catch (caught) {
          error = caught;
        }
        if (media) {
          if (under.dropped) return discard(media);
          const landed = media;
          const elsewhere = current.current
            .flat()
            .some((t) => t.state === 'ready' && t.media.id === landed.id);
          if (elsewhere) dropTile(key);
          else changeTile(key, (tile) => readyTile(key, landed, tile.localUrl));
          track('media_attached', { kind: landed.kind, via, source: 'web' });
          return;
        }
        if (errorCode(error) === RECONNECT_FOR_MEDIA) {
          if (under.dropped) return;
          dropTile(key);
          onReconnectNeeded();
          return;
        }
        // The Part went away on the server, by Feedback here or elsewhere: send it again.
        const partGone = errorStatus(error) === 404;
        const refusal = partGone ? { message: UPLOAD_FAILED, retry: true } : refusalOf(error);
        const server =
          refusal.retry || errorCode(error) === 'MEDIA_PART_FULL' ? await read() : null;
        if (server) {
          const known = new Set([
            ...current.current.flat().flatMap((t) => (t.state === 'ready' ? [t.media.id] : [])),
            ...discarded.current,
          ]);
          const unknown = server.flat().filter((m) => !known.has(m.id));
          const landed = refusal.retry && !partGone && unknown.length === 1 ? unknown[0]! : null;
          if (landed && under.dropped) {
            discarded.current.add(landed.id);
            reconcile(
              server.map((onPart) => onPart.filter((m) => m.id !== landed.id)),
              null,
            );
            return discard(landed);
          }
          reconcile(server, landed && { key, media: landed });
          if (landed) {
            track('media_attached', { kind: landed.kind, via, source: 'web' });
            return;
          }
          if (partGone && attempt === 0 && !under.dropped) continue;
        }
        if (under.dropped) return;
        changeTile(key, (tile) => ({
          key,
          state: 'refused',
          file,
          localUrl: tile.localUrl,
          refusal,
          via,
        }));
        return;
      }
    },
    [postId, partWith, changeTile, dropTile, read, reconcile, discard, onReconnectNeeded],
  );

  const upload = useCallback(
    (key: string, file: File, via: AttachVia) => {
      const under: Upload = { dropped: false };
      uploads.current.set(key, under);
      enqueue(async () => {
        try {
          if (!under.dropped) await send(key, file, via, under);
        } finally {
          uploads.current.delete(key);
        }
      });
    },
    [enqueue, send],
  );

  const roomOn = useCallback(
    (partIndex: number) =>
      isStored(partIndex)
        ? IMAGES_PER_PART - (current.current[partIndex] ?? []).filter(holdsPlace).length
        : 0,
    [isStored],
  );

  const attach = useCallback(
    (partIndex: number, files: File[], via: AttachVia) => {
      if (!isStored(partIndex)) return;
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
        upload(key, file, via);
      }
    },
    [change, isStored, newKey, roomOn, upload],
  );

  const retry = useCallback(
    (key: string) => {
      const tile = tileWith(key);
      if (tile?.state !== 'refused') return;
      if (roomOn(partWith(key)) <= 0) return;
      changeTile(key, () => ({
        key,
        state: 'uploading',
        file: tile.file,
        localUrl: tile.localUrl,
        progress: 0,
        via: tile.via,
      }));
      upload(key, tile.file, tile.via);
    },
    [tileWith, partWith, changeTile, roomOn, upload],
  );

  const remove = useCallback(
    (key: string) => {
      const tile = tileWith(key);
      if (!tile) return;
      if (tile.state !== 'ready') {
        const under = uploads.current.get(key);
        if (under) under.dropped = true;
        dropTile(key);
        return;
      }
      if (tile.removing) return;
      changeTile(key, (t) => ({ ...t, removing: true }) as Tile);
      const removed = () => {
        discarded.current.add(tile.media.id);
        dropTile(key);
        track('media_removed', { kind: tile.media.kind, source: 'web' });
      };
      enqueue(() =>
        mediaService.remove(postId, tile.media.id).then(removed, (error: unknown) => {
          // A read after a failed upload may already have found it gone.
          if (errorStatus(error) === 404) return removed();
          changeTile(key, (t) => ({ ...t, removing: false }) as Tile);
          showToast("Couldn't remove the image. Try again.");
        }),
      );
    },
    [postId, tileWith, changeTile, dropTile, enqueue],
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
