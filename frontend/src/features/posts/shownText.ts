import { xWeightedLength } from '@/lib/xLength';
import type { Part, PostDetail, PostText, Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { showsScheduledPost } from './postStatus';

/** One Part as the Version card shows it and Copy post copies it. */
export interface ShownPart {
  text: string;
  charCount: number;
  charLimit: number;
  /** Live on X in a Thread that failed partway, and so locked; marked only on a Failed Post. */
  live: boolean;
  xPostUrl: string | null;
}

const notLive = (part: Part): ShownPart => ({ ...part, live: false, xPostUrl: null });

/**
 * The text on screen for `version`. On the Version the Post's Text came from, a Failed Post shows
 * what a retry sends and any other Scheduled post its own copy, edits included, since that is
 * what goes or went to X; every other Version shows its own text.
 */
export function shownParts(
  version: Version,
  post: PostDetail,
  xCharLimit: number | null,
): ShownPart[] {
  if (showsScheduledPost(post, version) && post.text) {
    const { scheduledPost, text } = post;
    if (scheduledPost.state === 'failed') return retryParts(text, scheduledPost, xCharLimit);
    const charLimit = xCharLimit ?? version.parts[0]?.charLimit ?? 280;
    return scheduledPost.parts.map((part) => ({
      text: part.text,
      charCount: xWeightedLength(part.text),
      charLimit,
      live: false,
      xPostUrl: part.xPostUrl,
    }));
  }
  return version.parts.map(notLive);
}

/** The Post's Text, as "Post to…" sends it from a Draft. */
export function textParts(text: PostText): ShownPart[] {
  return text.parts.map(notLive);
}

/**
 * What retrying a Failed Post sends to X: the Parts already live stay first, as they are, and
 * the Text's Parts in their places are skipped, as the server does (ADR 0014).
 */
export function retryParts(
  text: PostText,
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
  return [...live, ...text.parts.slice(live.length).map(notLive)];
}

/** Every Part, as Copy post puts it on the clipboard. */
export function copiedText(parts: ShownPart[]): string {
  return parts.map((part) => part.text).join('\n\n');
}
