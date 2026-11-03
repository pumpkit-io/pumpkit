import { apiService } from './apiService';

/** What a Media is: X takes up to four images, or one GIF, or one video, on one X post. */
export type MediaKind = 'image' | 'gif' | 'video';

/** One Media on a Part of a Post's Text, published with that Part's X post. */
export interface Media {
  id: string;
  kind: MediaKind;
  /**
   * Under the API's root, served only to its owner, so it is read with the session's token. Null
   * for a video sent without its first frame, as an AI app sends one.
   */
  previewUrl: string | null;
  width: number | null;
  height: number | null;
  /** What an image or GIF shows, for screen readers; null until the User or their AI app writes it. */
  altText: string | null;
  /** A video's length as the browser read it on upload; null otherwise. */
  durationMs: number | null;
}

export interface MediaApi {
  id: string;
  kind: MediaKind;
  preview_url: string | null;
  width: number | null;
  height: number | null;
  alt_text: string | null;
  duration_ms: number | null;
}

export const toMedia = (m: MediaApi): Media => ({
  id: m.id,
  kind: m.kind,
  previewUrl: m.preview_url,
  width: m.width,
  height: m.height,
  altText: m.alt_text,
  durationMs: m.duration_ms,
});

/** What the browser read of a video, sent with it, since the server never reads one. */
export interface VideoFacts {
  durationMs: number | null;
  /** Its first frame, as an image. */
  poster: Blob | null;
}

/** X's limit on an image or GIF's alt text. */
export const ALT_TEXT_MAX_CHARS = 1000;

export interface UploadOptions {
  /** Hears the share of the upload sent so far, from 0 to 1, and how many bytes are left. */
  onProgress?: (sent: number, bytesLeft: number) => void;
  video?: VideoFacts | null;
  signal?: AbortSignal;
}

async function upload(
  path: string,
  file: File,
  { onProgress, video, signal }: UploadOptions,
): Promise<Media> {
  const form = new FormData();
  if (video?.durationMs != null) form.append('duration_ms', String(Math.round(video.durationMs)));
  if (video?.poster) form.append('poster', video.poster, 'poster.jpg');
  form.append('file', file);
  const { data } = await apiService.post<MediaApi>(path, form, {
    signal,
    // The browser fills in the boundary; the JSON default would send the form as JSON.
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (event: { loaded: number; total?: number }) => {
      if (event.total) onProgress?.(event.loaded / event.total, event.total - event.loaded);
    },
  });
  return toMedia(data);
}

export const mediaService = {
  /** Attaches `file` to Part `partNumber` (from 1) of the Post's Text, after its other Media. */
  attach: (
    postId: string,
    partNumber: number,
    file: File,
    options: UploadOptions = {},
  ): Promise<Media> =>
    upload(`/posts/${encodeURIComponent(postId)}/text/parts/${partNumber}/media`, file, options),
  remove: async (postId: string, mediaId: string): Promise<void> => {
    await apiService.delete(
      `/posts/${encodeURIComponent(postId)}/text/media/${encodeURIComponent(mediaId)}`,
    );
  },
  /**
   * Attaches `file` to Part `partNumber` (from 1) of a waiting Scheduled post's own copy, after
   * its other Media. The Post's Text keeps its own.
   */
  attachToScheduledPost: (
    scheduledPostId: string,
    partNumber: number,
    file: File,
    options: UploadOptions = {},
  ): Promise<Media> =>
    upload(
      `/scheduled-posts/${encodeURIComponent(scheduledPostId)}/parts/${partNumber}/media`,
      file,
      options,
    ),
  removeFromScheduledPost: async (scheduledPostId: string, mediaId: string): Promise<void> => {
    await apiService.delete(
      `/scheduled-posts/${encodeURIComponent(scheduledPostId)}/media/${encodeURIComponent(mediaId)}`,
    );
  },
  /** Sets an image or GIF's alt text on the Post's Text; empty or null clears it. */
  setAltText: async (postId: string, mediaId: string, altText: string | null): Promise<Media> => {
    const { data } = await apiService.put<MediaApi>(
      `/posts/${encodeURIComponent(postId)}/text/media/${encodeURIComponent(mediaId)}/alt-text`,
      { alt_text: altText },
    );
    return toMedia(data);
  },
  /** Sets an image or GIF's alt text on a waiting Scheduled post; empty or null clears it. */
  setScheduledPostAltText: async (
    scheduledPostId: string,
    mediaId: string,
    altText: string | null,
  ): Promise<Media> => {
    const { data } = await apiService.put<MediaApi>(
      `/scheduled-posts/${encodeURIComponent(scheduledPostId)}/media/${encodeURIComponent(mediaId)}/alt-text`,
      { alt_text: altText },
    );
    return toMedia(data);
  },
  /** The preview's image, fetched with the session's token, which an `<img>` can't send. */
  preview: async (previewUrl: string, signal?: AbortSignal): Promise<Blob> => {
    const { data } = await apiService.get<Blob>(previewUrl, { responseType: 'blob', signal });
    return data;
  },
  /**
   * The Media's whole file, fetched with the session's token. Gone once its Post is published,
   * and downloaded in full before a video can play.
   */
  file: async (mediaId: string, signal?: AbortSignal): Promise<Blob> => {
    const { data } = await apiService.get<Blob>(`/media/${encodeURIComponent(mediaId)}/file`, {
      responseType: 'blob',
      signal,
    });
    return data;
  },
};
