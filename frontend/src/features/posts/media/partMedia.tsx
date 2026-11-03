import { MediaButton } from './MediaButton';
import { MediaTiles, ReadOnlyMediaTiles } from './MediaTiles';
import { mediaWhere } from './mediaRules';
import { aMedia, kindOfTile, type TextMedia } from './useTextMedia';
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
          onRemove={media.remove}
          onRetry={media.retry}
          onDescribe={media.describe}
        />
      ),
      button: (
        <MediaButton
          where={where}
          full={media.roomOn(index) <= 0}
          saving={media.saving(index)}
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
    const part = parts[index];
    if (!part?.media.length) return null;
    return {
      tiles: (
        <ReadOnlyMediaTiles
          media={part.media}
          where={mediaWhere(index, parts.length)}
          onX={part.xPostUrl !== null}
        />
      ),
    };
  };
}

/** Why sending the Parts waits for their Media, or null when none is uploading or being removed. */
export function mediaWait(parts: ShownPart[], media: TextMedia): string | null {
  const tiles = parts.flatMap((part, index) => (part.live ? [] : media.tilesOf(index)));
  const uploading = tiles.find((tile) => tile.state === 'uploading');
  if (uploading) return `${aMedia(kindOfTile(uploading))} is still uploading`;
  const removing = tiles.find((tile) => tile.state === 'ready' && tile.removing);
  if (removing) return `${aMedia(kindOfTile(removing))} is still being removed`;
  return null;
}
