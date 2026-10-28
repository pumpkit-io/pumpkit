import type { PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

const when = new Intl.DateTimeFormat('en', {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});

/** A moment as the panels say it, in the browser's time zone: Mon, Oct 12, 9:00 AM. */
export function formatWhen(iso: string): string {
  return when.format(new Date(iso));
}

/** "Version n" of the Version the Scheduled post came from, or null for one typed before it. */
export function sourceVersionLabel(post: PostDetail, scheduledPost: ScheduledPost): string | null {
  const source = post.versions.find((v) => v.id === scheduledPost.sourceVersionId);
  return source ? `Version ${source.number}` : null;
}
