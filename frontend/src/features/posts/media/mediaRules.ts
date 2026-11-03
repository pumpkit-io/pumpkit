import { errorCode, errorMessage, errorStatus } from '@/services/apiErrors';
import type { Media, MediaKind } from '@/services/mediaService';

const KINDS_BY_TYPE: Record<string, MediaKind> = {
  'image/jpeg': 'image',
  'image/png': 'image',
  'image/webp': 'image',
  'image/gif': 'gif',
  'video/mp4': 'video',
  'video/quicktime': 'video',
};
/** For a file the browser names no type for, as some do for a MOV. */
const KINDS_BY_EXTENSION: Record<string, MediaKind> = {
  jpg: 'image',
  jpeg: 'image',
  png: 'image',
  webp: 'image',
  gif: 'gif',
  mp4: 'video',
  mov: 'video',
};

/** The types the file picker offers; the backend checks each file's bytes again. */
export const ACCEPTED_TYPES = [...Object.keys(KINDS_BY_TYPE), '.mov'];
const MB = 1024 * 1024;
export const MAX_BYTES: Record<MediaKind, number> = {
  image: 5 * MB,
  gif: 15 * MB,
  video: 512 * MB,
};
export const IMAGES_PER_PART = 4;

export const X_MEDIA_RULE = 'X takes up to 4 images, or 1 GIF, or 1 video, per post';
export const IMAGE_TYPE_REFUSED = 'JPEG, PNG, WEBP or GIF only';
export const VIDEO_TYPE_REFUSED = 'MP4 or MOV only';
export const UNREADABLE = "Can't read this image";
/** X takes longer videos only from Premium accounts. */
export const PREMIUM_VIDEO_MS = 20 * 60 * 1000;
export const LONG_VIDEO = 'Over 20 minutes: X takes longer videos only from Premium accounts.';
export const UPLOAD_FAILED = 'Upload failed. Try again.';
/** Why a Part an undo shows before it lands takes no files yet. */
export const PART_SAVING = "Saving this part. Add media once it's saved.";

export function tooLarge(kind: MediaKind): string {
  return `Larger than ${MAX_BYTES[kind] / MB} MB`;
}

/** The file's kind by its type, or its extension; null when Pumpkit can't take it. */
export function kindOfFile(file: File): MediaKind | null {
  if (file.type) return KINDS_BY_TYPE[file.type] ?? null;
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  return KINDS_BY_EXTENSION[extension] ?? null;
}

/** The kind as a tile names it: "image", "GIF" or "video". */
export function mediaNoun(kind: MediaKind): string {
  return kind === 'gif' ? 'GIF' : kind;
}

/** Whether one X post holding Media of `holding` kinds takes one of `kind` too. */
export function takesMore(holding: MediaKind[], kind: MediaKind): boolean {
  return !breaksKindsRule([...holding, kind]);
}

/** A video's length as X's player shows it: 0:42, 12:05 or 1:02:09. */
export function formatDuration(ms: number): string {
  const total = Math.round(ms / 1000);
  const seconds = String(total % 60).padStart(2, '0');
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}`
    : `${minutes}:${seconds}`;
}

function breaksKindsRule(kinds: MediaKind[]): boolean {
  if (kinds.some((kind) => kind !== 'image')) return kinds.length > 1;
  return kinds.length > IMAGES_PER_PART;
}

/** Whether one X post can't carry `media`, as the server checks before scheduling. */
export function breaksXMediaRule(media: Media[]): boolean {
  return breaksKindsRule(media.map((m) => m.kind));
}

/** Where Media goes, as its tiles' labels name it: "Part 2", or "the post" for a single post. */
export function mediaWhere(index: number, count: number): string {
  return count > 1 ? `Part ${index + 1}` : 'the post';
}

/** How the User attached a file, for analytics. */
export type AttachVia = 'button' | 'drop' | 'paste';

/** Why a file can't go on a Part, and whether sending it again could help. */
export interface Refusal {
  message: string;
  retry: boolean;
}

function typeRefused(file: File): string {
  return file.type.startsWith('video/') ? VIDEO_TYPE_REFUSED : IMAGE_TYPE_REFUSED;
}

/** Refuses what the backend would before sending it: the type the browser names, and the size. */
export function refusalBeforeUpload(file: File): Refusal | null {
  const kind = kindOfFile(file);
  if (!kind) return { message: typeRefused(file), retry: false };
  if (file.size > MAX_BYTES[kind]) return { message: tooLarge(kind), retry: false };
  return null;
}

/** A tile's words on a failed upload of `file`: the server's refusal, or a retryable failure. */
export function refusalOf(error: unknown, file: File): Refusal {
  const refusals: Record<string, string> = {
    MEDIA_TYPE_UNSUPPORTED: typeRefused(file),
    MEDIA_TOO_LARGE: tooLarge(kindOfFile(file) ?? 'image'),
    MEDIA_UNREADABLE: UNREADABLE,
    MEDIA_PART_FULL: X_MEDIA_RULE,
  };
  const code = errorCode(error);
  if (code && code in refusals) return { message: refusals[code]!, retry: false };
  const status = errorStatus(error);
  // Another refusal, such as a Post scheduled meanwhile, says itself.
  if (status !== null && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    const message = errorMessage(error, UPLOAD_FAILED);
    return { message, retry: message === UPLOAD_FAILED };
  }
  return { message: UPLOAD_FAILED, retry: true };
}
