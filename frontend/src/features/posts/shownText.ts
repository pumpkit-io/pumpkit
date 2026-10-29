import { xWeightedLength } from '@/lib/xLength';
import type { PostDetail, Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { hasScheduledPost } from './postStatus';

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
 * The text on screen for `version`: the Scheduled post's copy when it came from this Version,
 * since that is what goes or went to X, edits included; else the Version's own text.
 */
export function shownParts(
  version: Version,
  scheduledPost: ScheduledPost | null,
  xCharLimit: number | null,
): ShownPart[] {
  if (hasScheduledPost(scheduledPost, version.id)) {
    const charLimit = xCharLimit ?? version.parts[0]?.charLimit ?? 280;
    const failed = scheduledPost.state === 'failed';
    return scheduledPost.parts.map((part) => ({
      text: part.text,
      charCount: xWeightedLength(part.text),
      charLimit,
      live: failed && part.live,
      xPostUrl: part.xPostUrl,
    }));
  }
  return version.parts.map((part) => ({ ...part, live: false, xPostUrl: null }));
}

/**
 * What retrying a Failed Post with `version` sends to X: the Parts already live stay first, as
 * they are, and the Version's Parts in their places are skipped, as the server does (ADR 0014).
 * On the Version the Failed one came from, its own text, edits included.
 */
export function retryParts(
  version: Version,
  scheduledPost: ScheduledPost,
  xCharLimit: number | null,
): ShownPart[] {
  if (scheduledPost.sourceVersionId === version.id) {
    return shownParts(version, scheduledPost, xCharLimit);
  }
  const charLimit = xCharLimit ?? version.parts[0]?.charLimit ?? 280;
  const live: ShownPart[] = scheduledPost.parts
    .filter((part) => part.live)
    .map((part) => ({
      text: part.text,
      charCount: xWeightedLength(part.text),
      charLimit,
      live: true,
      xPostUrl: part.xPostUrl,
    }));
  const rest = version.parts
    .slice(live.length)
    .map((part) => ({ ...part, live: false, xPostUrl: null }));
  return [...live, ...rest];
}

/**
 * The Post's Text as the Version it came from, so what sends a Version sends the Text; the
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
