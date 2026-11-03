import { errorCode, errorMessage, errorStatus } from '@/services/apiErrors';

/** The types the file picker offers; the backend checks each file's bytes again. */
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const IMAGE_MAX_BYTES = 5 * 1024 * 1024;
export const IMAGES_PER_PART = 4;

export const X_MEDIA_RULE = 'X takes up to 4 images, or 1 GIF, or 1 video, per post';
export const TOO_LARGE = 'Larger than 5 MB';
export const TYPE_REFUSED = 'JPEG, PNG or WEBP only';
export const UNREADABLE = "Can't read this image";
export const UPLOAD_FAILED = 'Upload failed. Try again.';

/** How the User attached a file, for analytics. */
export type AttachVia = 'button' | 'drop' | 'paste';

/** Why a file can't go on a Part, and whether sending it again could help. */
export interface Refusal {
  message: string;
  retry: boolean;
}

/** Refuses what the backend would before sending it: the type the browser names, and the size. */
export function refusalBeforeUpload(file: File): Refusal | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return { message: TYPE_REFUSED, retry: false };
  if (file.size > IMAGE_MAX_BYTES) return { message: TOO_LARGE, retry: false };
  return null;
}

const REFUSALS: Record<string, string> = {
  MEDIA_TYPE_UNSUPPORTED: TYPE_REFUSED,
  MEDIA_TOO_LARGE: TOO_LARGE,
  MEDIA_UNREADABLE: UNREADABLE,
  MEDIA_PART_FULL: X_MEDIA_RULE,
};

/** What a tile says of a failed upload: the backend's refusal, or a failure worth retrying. */
export function refusalOf(error: unknown): Refusal {
  const code = errorCode(error);
  if (code && code in REFUSALS) return { message: REFUSALS[code]!, retry: false };
  const status = errorStatus(error);
  // Another refusal, such as a Post scheduled meanwhile, says itself.
  if (status !== null && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    const message = errorMessage(error, UPLOAD_FAILED);
    return { message, retry: message === UPLOAD_FAILED };
  }
  return { message: UPLOAD_FAILED, retry: true };
}
