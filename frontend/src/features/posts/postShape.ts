// How Parts read from their count and first reply flag (ADR 0027), as `posts/formats.py` says.
import { FORMAT_POST, formatOf, type Format } from '@/services/postService';

/** How many of the first Parts take Media: every one but a first reply. */
export function mediaPartCount(partCount: number, firstReply: boolean): number {
  return firstReply ? partCount - 1 : partCount;
}

/** What the page calls Part `index`: "First reply", "Part 2" in a Thread, or "Post". */
export function partName(index: number, partCount: number, firstReply: boolean): string {
  if (firstReply && index === partCount - 1) return 'First reply';
  return formatOf(partCount, firstReply) === FORMAT_POST ? 'Post' : `Part ${index + 1}`;
}

/** How a screen reader names Part `index` in a list: "Part 2 of 3" in a Thread. */
export function partLabel(index: number, partCount: number, firstReply: boolean): string {
  const name = partName(index, partCount, firstReply);
  return formatOf(partCount, firstReply) === FORMAT_POST ? name : `${name} of ${partCount}`;
}

/** Part `index` as a sentence's subject: "Part 2", "The post" or "The first reply". */
export function partSubject(index: number, partCount: number, firstReply: boolean): string {
  const name = partName(index, partCount, firstReply);
  return formatOf(partCount, firstReply) === FORMAT_POST ? `The ${name.toLowerCase()}` : name;
}

/** What the Text is, as a list row or a dialog says it: "Single post · first reply". */
export function shapeName(partCount: number, firstReply: boolean): string {
  if (formatOf(partCount, firstReply) !== FORMAT_POST) return `Thread · ${partCount} parts`;
  return firstReply ? 'Single post · first reply' : 'Single post';
}

/**
 * Whether edited Parts of a Text in `format` end with a first reply: an edit keeps a single post
 * single, so a Part after the post can only be its first reply.
 */
export function endsWithFirstReply(format: Format, partCount: number): boolean {
  return format === FORMAT_POST && partCount > 1;
}
