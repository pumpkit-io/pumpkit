import { xWeightedLength } from '@/lib/xLength';
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
}

/**
 * What retrying a Failed Post sends to X: the Parts already live stay first, as they are, and
 * the Text's Parts in their places are skipped, as the server does (ADR 0014).
 */
export function retryParts(
  text: Pick<Version, 'parts'>,
  scheduledPost: ScheduledPost,
  xCharLimit: number | null,
): ShownPart[] {
  const charLimit = xCharLimit ?? text.parts[0]?.charLimit ?? 280;
  const live: ShownPart[] = scheduledPost.parts
    .filter((part) => part.live)
    .map((part) => ({
      text: part.text,
      charCount: xWeightedLength(part.text),
      charLimit,
      live: true,
      xPostUrl: part.xPostUrl,
    }));
  const rest = text.parts
    .slice(live.length)
    .map((part) => ({ ...part, live: false, xPostUrl: null }));
  return [...live, ...rest];
}

/**
 * The Post's Text as the Version it came from, for what reads a Version's shape; the
 * latest Version for a Post with no Text.
 */
export function textVersionOf(post: PostDetail): Version | undefined {
  const latest = post.versions[post.versions.length - 1];
  const { text } = post;
  if (!text) return latest;
  const source = post.versions.find((v) => v.number === text.versionNumber) ?? latest;
  return source && { ...source, format: text.format, parts: text.parts };
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
  if (!scheduledPost) return textVersion.parts.map((p) => ({ ...p, live: false, xPostUrl: null }));
  if (scheduledPost.state === 'failed') return retryParts(textVersion, scheduledPost, xCharLimit);
  const charLimit = xCharLimit ?? textVersion.parts[0]?.charLimit ?? 280;
  return scheduledPost.parts.map((part) => ({
    text: part.text,
    charCount: xWeightedLength(part.text),
    charLimit,
    live: false,
    xPostUrl: part.xPostUrl,
  }));
}

/** Every Part, as Copy puts it on the clipboard: a Thread's Parts split by a line of `---`. */
export function copiedText(parts: ShownPart[]): string {
  return parts.map((part) => part.text).join('\n\n---\n\n');
}
