import { X_POST_MAX_CHARS, xWeightedLength } from '@/lib/xLength';
import type { Media } from '@/services/mediaService';
import type { PostDetail, Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

/** One Part as the Version card shows it and Copy post copies it. */
export interface ShownPart {
  text: string;
  charCount: number;
  charLimit: number;
  /** Live on X in a Thread that failed partway, and so locked; marked only on a Failed Post. */
  live: boolean;
  xPostUrl: string | null;
  /** What goes out with it; the Text's Media is filled in by the page that holds it. */
  media: Media[];
  /** The single post's first reply, its last Part, which goes out as a reply to it. */
  firstReply: boolean;
}

/** Marks the last of `parts` as a first reply when `firstReply` says it is one. */
function withFirstReply(parts: Omit<ShownPart, 'firstReply'>[], firstReply: boolean): ShownPart[] {
  return parts.map((part, i) => ({ ...part, firstReply: firstReply && i === parts.length - 1 }));
}

/**
 * What retrying a Failed Post sends to X: the Parts already live stay first, as they are, and
 * the Text's Parts in their places are skipped, as the server does (ADR 0014).
 */
export function retryParts(
  text: Pick<Version, 'parts' | 'firstReply'>,
  scheduledPost: ScheduledPost,
  xCharLimit: number | null,
): ShownPart[] {
  const charLimit = xCharLimit ?? text.parts[0]?.charLimit ?? X_POST_MAX_CHARS;
  const live = scheduledPost.parts
    .filter((part) => part.live)
    .map((part) => ({
      text: part.text,
      charCount: xWeightedLength(part.text),
      charLimit,
      live: true,
      xPostUrl: part.xPostUrl,
      media: part.media,
    }));
  const rest = text.parts
    .slice(live.length)
    .map((part) => ({ ...part, live: false, xPostUrl: null, media: [] }));
  return withFirstReply([...live, ...rest], text.firstReply);
}

/**
 * The text the Post's card shows: what goes or went to X once it has a Scheduled post, the live
 * Parts first on a Failed one, else the Text.
 */
export function cardParts(
  post: PostDetail,
  textVersion: Version,
  xCharLimit: number | null,
): ShownPart[] {
  const { scheduledPost } = post;
  if (!scheduledPost) {
    return withFirstReply(
      textVersion.parts.map((p) => ({ ...p, live: false, xPostUrl: null, media: [] })),
      textVersion.firstReply,
    );
  }
  if (scheduledPost.state === 'failed') return retryParts(textVersion, scheduledPost, xCharLimit);
  const charLimit = xCharLimit ?? textVersion.parts[0]?.charLimit ?? X_POST_MAX_CHARS;
  return withFirstReply(
    scheduledPost.parts.map((part) => ({
      text: part.text,
      charCount: xWeightedLength(part.text),
      charLimit,
      live: false,
      xPostUrl: part.xPostUrl,
      media: part.media,
    })),
    scheduledPost.firstReply,
  );
}

/**
 * What the page calls Part `index`: "First reply", "Part 2" in a Thread, or "Post" for a single
 * post, with or without its first reply.
 */
export function partName(parts: ShownPart[], index: number): string {
  if (parts[index]?.firstReply) return 'First reply';
  const inThread = parts.filter((part) => !part.firstReply).length > 1;
  return inThread ? `Part ${index + 1}` : 'Post';
}

/** Every Part, as Copy puts it on the clipboard: a Thread's Parts split by a line of `---`. */
export function copiedText(parts: ShownPart[]): string {
  return parts.map((part) => part.text).join('\n\n---\n\n');
}
