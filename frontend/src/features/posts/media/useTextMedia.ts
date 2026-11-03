import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { showToast } from '@/components/Toaster';
import { track } from '@/lib/analytics';
import { useConfirmLeaving } from '@/lib/useConfirmLeaving';
import { errorCode, errorStatus } from '@/services/apiErrors';
import type { Media, MediaKind, VideoFacts } from '@/services/mediaService';
import {
  IMAGES_PER_PART,
  PART_SAVING,
  UPLOAD_FAILED,
  X_MEDIA_RULE,
  kindOfFile,
  mediaNoun,
  refusalBeforeUpload,
  refusalOf,
  takesMore,
  type AttachVia,
  type Refusal,
} from './mediaRules';
import { textMediaPlace, type MediaPlace } from './mediaPlaces';
import { localUrlOf } from './useMediaPreview';
import { readVideo } from './videoFile';

/** One file on a Part as the card shows it, from the moment it is chosen. */
export type Tile =
  | {
      key: string;
      state: 'uploading';
      file: File;
      kind: MediaKind;
      /** The chosen file itself, or a video's first frame, shown until the stored preview loads. */
      localUrl: string | null;
      /** A video's length, once the browser read it. */
      durationMs: number | null;
      /** A video whose length and first frame the browser is still reading. */
      reading: boolean;
      /** The share sent so far, from 0 to 1. */
      progress: number;
      via: AttachVia;
    }
  | {
      key: string;
      state: 'ready';
      media: Media;
      localUrl: string | null;
      /** The file picked in this session. */
      file: File | null;
      removing: boolean;
    }
  | {
      key: string;
      state: 'refused';
      file: File;
      kind: MediaKind;
      localUrl: string | null;
      durationMs: number | null;
      refusal: Refusal;
      via: AttachVia;
    };

export interface TextMedia {
  /** The Part's tiles in order, refused files included. */
  tilesOf: (partIndex: number) => Tile[];
  /** How many more images the Part takes; none once it holds a GIF or a video. */
  roomOn: (partIndex: number) => number;
  /** Whether the Part is one an undo shows before it lands, which takes no files yet. */
  saving: (partIndex: number) => boolean;
  attach: (partIndex: number, files: File[], via: AttachVia) => void;
  remove: (key: string) => void;
  retry: (key: string) => void;
  /** Sets a ready image's alt text, null clearing it; rejects when the server didn't take it. */
  describe: (key: string, altText: string | null) => Promise<void>;
}

/** Whether a tile counts toward what X takes on one X post. */
export function holdsPlace(tile: Tile): boolean {
  return tile.state === 'uploading' || (tile.state === 'ready' && !tile.removing);
}

export function kindOfTile(tile: Tile): MediaKind {
  return tile.state === 'ready' ? tile.media.kind : tile.kind;
}

const RECONNECT_FOR_MEDIA = 'X_RECONNECT_FOR_MEDIA';

/** "An image", "A GIF" or "A video". */
export function aMedia(kind: MediaKind): string {
  return kind === 'image' ? 'An image' : `A ${mediaNoun(kind)}`;
}

/** Progress events lag the bytes sent: only this much left proves the server lacks the file. */
const ABORTABLE_BYTES_LEFT = 32 * 1024 * 1024;

/**
 * An upload, queued or under way. A stopped one finishes and its Media is taken off, unless it
 * is a video known to have far to go: aborting it can't leave a Media behind.
 */
interface Upload {
  kind: MediaKind;
  /** Stopped by the User or by leaving the page. */
  dropped: boolean;
  /** Null until the browser reports progress. */
  bytesLeft: number | null;
  controller: AbortController;
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
  file: File | null,
): Extract<Tile, { state: 'ready' }> {
  return { key, state: 'ready', media, localUrl, file, removing: false };
}

/** Drops an upload; a video with far to go stops at once. */
function stop(under: Upload) {
  under.dropped = true;
  if (
    under.kind === 'video' &&
    under.bytesLeft !== null &&
    under.bytesLeft >= ABORTABLE_BYTES_LEFT
  ) {
    under.controller.abort();
  }
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
  /** Where the Media lives instead of the Text, such as a Scheduled post's own copy. */
  placeInstead?: MediaPlace,
): TextMedia {
  const place = useMemo(() => placeInstead ?? textMediaPlace(postId), [placeInstead, postId]);
  const nextKey = useRef(0);
  const newKey = useCallback(() => `tile-${++nextKey.current}`, []);
  const [parts, setParts] = useState<Tile[][]>(() =>
    initial.map((onPart) => onPart.map((media) => readyTile(newKey(), media, null, null))),
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
  /** Each video's length and first frame, read in the browser as it is chosen. */
  const videoReads = useRef(new Map<string, Promise<VideoFacts>>());
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
      await place.remove(media.id).catch(() => {});
    },
    [place],
  );

  /**
   * The Media on each Part as the server holds it, or null when it can't be read. Never more Parts
   * than `partCount`, and exactly that many when the Text changed while the read was under way.
   */
  const read = useCallback(async (): Promise<Media[][] | null> => {
    const changesBefore = partCountChanges.current;
    let text: Media[][];
    try {
      text = await place.read();
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
  }, [place]);

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
        shown.set(
          claimed.media.id,
          readyTile(claimed.key, claimed.media, claimedTile.localUrl, claimedTile.file),
        );
      }
      const onServer = new Set(server.flat().map((m) => m.id));
      tiles.filter((t) => t.state === 'ready' && !onServer.has(t.media.id)).forEach(release);
      const pending = folded(current.current, server.length).map((onPart) =>
        onPart.filter((t) => t.state !== 'ready' && t.key !== claimed?.key),
      );
      set(
        server.map((onPart, index) => [
          ...onPart.map((media) => shown.get(media.id) ?? readyTile(newKey(), media, null, null)),
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
      const video = (await videoReads.current.get(key)) ?? null;
      for (let attempt = 0; ; attempt++) {
        const changesBefore = partCountChanges.current;
        const sentTo = partWith(key);
        if (sentTo === -1 || under.dropped) return;
        let media: Media | null = null;
        let error: unknown = null;
        try {
          media = await place.attach(sentTo + 1, file, {
            onProgress: (sent, bytesLeft) => {
              under.bytesLeft = bytesLeft;
              changeTile(key, (tile) =>
                tile.state === 'uploading' ? { ...tile, progress: sent } : tile,
              );
            },
            video,
            signal: under.controller.signal,
          });
        } catch (caught) {
          error = caught;
        }
        if (under.dropped && axios.isCancel(error)) {
          // Aborted far from the end, so the server can't have attached it. Media the
          // read finds that the page didn't know of came from elsewhere, such as an AI app: shown.
          const server = await read();
          if (server) reconcile(server, null);
          return;
        }
        if (media) {
          const landed = media;
          // A fold while it was sent may have put the tile ahead of Media the server put first.
          const server =
            under.dropped || changesBefore === partCountChanges.current ? null : await read();
          if (under.dropped) {
            if (server)
              reconcile(
                server.map((on) => on.filter((m) => m.id !== landed.id)),
                null,
              );
            return discard(landed);
          }
          const elsewhere = current.current
            .flat()
            .some((t) => t.state === 'ready' && t.media.id === landed.id);
          if (server) reconcile(server, { key, media: landed });
          else if (elsewhere) dropTile(key);
          else changeTile(key, (tile) => readyTile(key, landed, tile.localUrl, tile.file));
          track('media_attached', { kind: landed.kind, via, on: place.holder, source: 'web' });
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
        const refusal = partGone ? { message: UPLOAD_FAILED, retry: true } : refusalOf(error, file);
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
            track('media_attached', { kind: landed.kind, via, on: place.holder, source: 'web' });
            return;
          }
          if (partGone && attempt === 0 && !under.dropped) continue;
        }
        if (under.dropped) return;
        changeTile(key, (tile) =>
          tile.state === 'uploading'
            ? {
                key,
                state: 'refused',
                file,
                kind: tile.kind,
                localUrl: tile.localUrl,
                durationMs: tile.durationMs,
                refusal,
                via,
              }
            : tile,
        );
        return;
      }
    },
    [place, partWith, changeTile, dropTile, read, reconcile, discard, onReconnectNeeded],
  );

  const upload = useCallback(
    (key: string, file: File, kind: MediaKind, via: AttachVia) => {
      const under: Upload = {
        kind,
        dropped: false,
        bytesLeft: null,
        controller: new AbortController(),
      };
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

  const kindsOn = useCallback(
    (partIndex: number) => (current.current[partIndex] ?? []).filter(holdsPlace).map(kindOfTile),
    [],
  );

  const roomOn = useCallback(
    (partIndex: number) => {
      if (!isStored(partIndex)) return 0;
      const kinds = kindsOn(partIndex);
      return kinds.some((kind) => kind !== 'image') ? 0 : IMAGES_PER_PART - kinds.length;
    },
    [isStored, kindsOn],
  );

  /** Reads a chosen video's length and first frame, shown on its tile and sent with it. */
  const readVideoOf = useCallback(
    (key: string, file: File) => {
      const reading = readVideo(file);
      videoReads.current.set(key, reading);
      void reading.then(({ durationMs, poster }) => {
        const localUrl = poster ? localUrlOf(poster) : null;
        if (!tileWith(key)) {
          if (localUrl) URL.revokeObjectURL(localUrl);
          return;
        }
        changeTile(key, (tile) =>
          tile.state === 'ready'
            ? { ...tile, localUrl }
            : tile.state === 'uploading'
              ? { ...tile, localUrl, durationMs, reading: false }
              : { ...tile, localUrl, durationMs },
        );
      });
    },
    [tileWith, changeTile],
  );

  const attach = useCallback(
    (partIndex: number, files: File[], via: AttachVia) => {
      if (!isStored(partIndex)) {
        showToast(PART_SAVING);
        return;
      }
      for (const file of files) {
        const key = newKey();
        const kind = kindOfFile(file) ?? 'image';
        const video = kind === 'video';
        const localUrl = video ? null : localUrlOf(file);
        const refusal =
          refusalBeforeUpload(file) ??
          (isStored(partIndex) && takesMore(kindsOn(partIndex), kind)
            ? null
            : { message: X_MEDIA_RULE, retry: false });
        const shown = { key, file, kind, localUrl, durationMs: null, via };
        if (refusal) {
          change(partIndex, (tiles) => [...tiles, { ...shown, state: 'refused', refusal }]);
          continue;
        }
        change(partIndex, (tiles) => [
          ...tiles,
          { ...shown, state: 'uploading', reading: video, progress: 0 },
        ]);
        if (video) readVideoOf(key, file);
        upload(key, file, kind, via);
      }
    },
    [change, isStored, kindsOn, newKey, readVideoOf, upload],
  );

  const retry = useCallback(
    (key: string) => {
      const tile = tileWith(key);
      if (tile?.state !== 'refused') return;
      if (!takesMore(kindsOn(partWith(key)), tile.kind)) return;
      changeTile(key, () => ({
        key,
        state: 'uploading',
        file: tile.file,
        kind: tile.kind,
        localUrl: tile.localUrl,
        durationMs: tile.durationMs,
        reading: false,
        progress: 0,
        via: tile.via,
      }));
      upload(key, tile.file, tile.kind, tile.via);
    },
    [tileWith, partWith, changeTile, kindsOn, upload],
  );

  const remove = useCallback(
    (key: string) => {
      const tile = tileWith(key);
      if (!tile) return;
      if (tile.state !== 'ready') {
        const under = uploads.current.get(key);
        if (under) stop(under);
        videoReads.current.delete(key);
        dropTile(key);
        return;
      }
      if (tile.removing) return;
      changeTile(key, (t) => ({ ...t, removing: true }) as Tile);
      const removed = () => {
        discarded.current.add(tile.media.id);
        dropTile(key);
        track('media_removed', { kind: tile.media.kind, on: place.holder, source: 'web' });
      };
      enqueue(() =>
        place.remove(tile.media.id).then(removed, (error: unknown) => {
          // A read after a failed upload may already have found it gone.
          if (errorStatus(error) === 404) return removed();
          changeTile(key, (t) => ({ ...t, removing: false }) as Tile);
          showToast(`Couldn't remove the ${mediaNoun(tile.media.kind)}. Try again.`);
        }),
      );
    },
    [place, tileWith, changeTile, dropTile, enqueue],
  );

  const describe = useCallback(
    async (key: string, altText: string | null) => {
      const tile = tileWith(key);
      if (tile?.state !== 'ready') return;
      const media = await place.setAltText(tile.media.id, altText);
      changeTile(key, (t) => (t.state === 'ready' ? { ...t, media } : t));
      track('media_alt_text_set', {
        kind: media.kind,
        cleared: altText === null,
        on: place.holder,
        source: 'web',
      });
    },
    [place, tileWith, changeTile],
  );

  const uploading = parts.flat().find((tile) => tile.state === 'uploading');
  useConfirmLeaving(
    Boolean(uploading),
    `${aMedia(uploading ? kindOfTile(uploading) : 'image')} is still uploading. If you leave, it won't stay on the post. Leave anyway?`,
  );

  useEffect(
    () => () => {
      uploads.current.forEach(stop);
      current.current.flat().forEach(release);
    },
    [],
  );

  return {
    tilesOf: (partIndex) => parts[partIndex] ?? [],
    roomOn,
    saving: (partIndex) => !isStored(partIndex),
    attach,
    remove,
    retry,
    describe,
  };
}
