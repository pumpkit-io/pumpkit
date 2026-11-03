import { MediaButton } from './MediaButton';
import { MediaTiles, ReadOnlyMediaTiles } from './MediaTiles';
import { mediaWhere } from './mediaRules';
import type { TextMedia } from './useTextMedia';
import type { ShownPart } from '../shownText';
import type { PartMedia } from '../TextCard';

/**
 * Media controls for each Part not yet live on X. With `askToReconnect`, the media
 * button, a drop and a paste each ask to reconnect X instead of taking files.
 */
export function partMediaOf(
  media: TextMedia,
  parts: ShownPart[],
  askToReconnect: (() => void) | undefined,
) {
  return (index: number): PartMedia | null => {
    if (parts[index]?.live) return readOnlyMediaOf(parts)(index);
    const where = mediaWhere(index, parts.length);
    return {
      tiles: (
        <MediaTiles
          tiles={media.tilesOf(index)}
          where={where}
          canRetry={media.roomOn(index) > 0}
          onRemove={(key) => media.remove(key)}
          onRetry={(key) => media.retry(key)}
        />
      ),
      button: (
        <MediaButton
          where={where}
          full={media.roomOn(index) <= 0}
          onFiles={(files) => media.attach(index, files, 'button')}
          onClickInsteadOfPicker={askToReconnect}
        />
      ),
      onFiles: (files, via) =>
        askToReconnect ? askToReconnect() : media.attach(index, files, via),
    };
  };
}

/** The Media each Part goes, or went, to X with, shown as it is. */
export function readOnlyMediaOf(parts: ShownPart[]) {
  return (index: number): PartMedia | null => {
    const shown = parts[index]?.media ?? [];
    if (!shown.length) return null;
    return { tiles: <ReadOnlyMediaTiles media={shown} where={mediaWhere(index, parts.length)} /> };
  };
}

/** Why sending the Parts waits for their Media, or null when none is uploading or being removed. */
export function mediaWait(parts: ShownPart[], media: TextMedia): string | null {
  const tiles = parts.flatMap((part, index) => (part.live ? [] : media.tilesOf(index)));
  if (tiles.some((tile) => tile.state === 'uploading')) return 'An image is still uploading';
  if (tiles.some((tile) => tile.state === 'ready' && tile.removing)) {
    return 'An image is still being removed';
  }
  return null;
}
