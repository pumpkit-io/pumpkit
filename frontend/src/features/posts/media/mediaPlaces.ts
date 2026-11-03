import { mediaService, type Media, type UploadOptions } from '@/services/mediaService';
import { postService } from '@/services/postService';

/** Where a Part's Media lives on the server: the Post's Text, or a Scheduled post's own copy. */
export interface MediaPlace {
  attach: (partNumber: number, file: File, options: UploadOptions) => Promise<Media>;
  remove: (mediaId: string) => Promise<void>;
  /** Each Part's Media as the server holds it now. */
  read: () => Promise<Media[][]>;
}

export function textMediaPlace(postId: string): MediaPlace {
  return {
    attach: (partNumber, file, options) => mediaService.attach(postId, partNumber, file, options),
    remove: (mediaId) => mediaService.remove(postId, mediaId),
    read: async () => (await postService.get(postId)).textMedia,
  };
}

export function scheduledPostMediaPlace(postId: string, scheduledPostId: string): MediaPlace {
  return {
    attach: (partNumber, file, options) =>
      mediaService.attachToScheduledPost(scheduledPostId, partNumber, file, options),
    remove: (mediaId) => mediaService.removeFromScheduledPost(scheduledPostId, mediaId),
    read: async () =>
      (await postService.get(postId)).scheduledPost?.parts.map((part) => part.media) ?? [],
  };
}
