import { apiService } from './apiService';

/** What a Media is: X takes up to four images, or one GIF, or one video, on one X post. */
export type MediaKind = 'image' | 'gif' | 'video';

/** One Media on a Part of a Post's Text, published with that Part's X post. */
export interface Media {
  id: string;
  kind: MediaKind;
  /** Under the API's root, served only to its owner, so it is read with the session's token. */
  previewUrl: string;
  width: number | null;
  height: number | null;
}

export interface MediaApi {
  id: string;
  kind: MediaKind;
  preview_url: string;
  width: number | null;
  height: number | null;
}

export const toMedia = (m: MediaApi): Media => ({
  id: m.id,
  kind: m.kind,
  previewUrl: m.preview_url,
  width: m.width,
  height: m.height,
});

export const mediaService = {
  /**
   * Attaches `file` to Part `partNumber` (from 1) of the Post's Text, after its other Media.
   * `onProgress` hears the share of the file sent so far, from 0 to 1.
   */
  attach: async (
    postId: string,
    partNumber: number,
    file: File,
    { onProgress, signal }: { onProgress?: (sent: number) => void; signal?: AbortSignal } = {},
  ): Promise<Media> => {
    const form = new FormData();
    form.append('file', file);
    const { data } = await apiService.post<MediaApi>(
      `/posts/${encodeURIComponent(postId)}/text/parts/${partNumber}/media`,
      form,
      {
        // The browser fills in the boundary; the JSON default would send the form as JSON.
        headers: { 'Content-Type': 'multipart/form-data' },
        signal,
        onUploadProgress: (event: { loaded: number; total?: number }) => {
          if (event.total) onProgress?.(event.loaded / event.total);
        },
      },
    );
    return toMedia(data);
  },
  remove: async (postId: string, mediaId: string): Promise<void> => {
    await apiService.delete(
      `/posts/${encodeURIComponent(postId)}/text/media/${encodeURIComponent(mediaId)}`,
    );
  },
  /** The preview's image, fetched with the session's token, which an `<img>` can't send. */
  preview: async (previewUrl: string, signal?: AbortSignal): Promise<Blob> => {
    const { data } = await apiService.get<Blob>(previewUrl, { responseType: 'blob', signal });
    return data;
  },
};
