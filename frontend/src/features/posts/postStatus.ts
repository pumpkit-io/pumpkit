import type { PostStatus } from '@/services/postService';
import type { ScheduledPost, ScheduledPostState } from '@/services/scheduledPostService';

/** As the backend derives it (ADR 0015), for a Scheduled post the page just changed. */
export function statusFrom(state: ScheduledPostState | null): PostStatus {
  if (state === null) return 'draft';
  if (state === 'published' || state === 'failed') return state;
  return 'scheduled';
}

/** The status as a word, as the breadcrumb, the pager and the panels say it. */
export const STATUS_LABEL: Record<PostStatus, string> = {
  draft: 'Draft',
  scheduled: 'Scheduled',
  published: 'Published',
  failed: 'Failed',
};

/** The Posts tab each status lists under, named as its tab is. */
export const STATUS_TAB: Record<PostStatus, { label: string; path: string }> = {
  draft: { label: 'Drafts', path: '/posts/drafts' },
  scheduled: { label: 'Scheduled', path: '/posts/scheduled' },
  published: { label: 'Published', path: '/posts/published' },
  failed: { label: 'Failed', path: '/posts/failed' },
};

/** The Posts tabs in the order they sit, Scheduled first: what goes out next is what to check. */
export const TAB_ORDER: PostStatus[] = ['scheduled', 'draft', 'published', 'failed'];

/** How each tab orders its Posts, as the line under the tabs says it. */
export const TAB_ORDER_LINE: Record<PostStatus, string> = {
  scheduled: 'Next to go out first.',
  draft: 'Newest Version first.',
  published: 'Most recently published first.',
  failed: 'Most recently due first.',
};

const TITLE_MAX_CHARS = 60;

/** The first line of the text, cut on a word with an ellipsis when it runs long. */
export function postTitle(text: string): string {
  const firstLine = text.trim().split('\n')[0]?.trim() ?? '';
  if (firstLine.length <= TITLE_MAX_CHARS) return firstLine;
  const cut = firstLine.slice(0, TITLE_MAX_CHARS);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > 0 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

/** Whether `scheduledPost` was copied from the Version with `versionId`. */
export function hasScheduledPost(
  scheduledPost: ScheduledPost | null,
  versionId: string,
): scheduledPost is ScheduledPost {
  return scheduledPost !== null && scheduledPost.sourceVersionId === versionId;
}
