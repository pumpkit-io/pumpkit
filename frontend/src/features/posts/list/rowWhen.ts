import type { PostListItem } from '@/services/postService';

const DAY_MS = 24 * 60 * 60 * 1000;
const weekday = new Intl.DateTimeFormat('en', { weekday: 'short' });
const date = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' });
const time = new Intl.DateTimeFormat('en', { hour: 'numeric', minute: '2-digit' });

/** Calendar days from `now` to `then` in the browser's time zone: 1 is tomorrow. */
function daysBetween(then: Date, now: Date): number {
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((midnight(then) - midnight(now)) / DAY_MS);
}

/** Today, Tomorrow, In 3 days, 2 days ago, or the weekday when it is over a week away. */
export function relativeDay(then: Date, now: Date = new Date()): string {
  const days = daysBetween(then, now);
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days === -1) return 'Yesterday';
  if (days > 1 && days < 7) return `In ${days} days`;
  if (days < -1 && days > -7) return `${-days} days ago`;
  return weekday.format(then);
}

/** The moment a row is listed by: what its tab sorts on. */
export function rowMoment(post: PostListItem): string {
  const scheduled = post.scheduledPost;
  if (!scheduled) return post.latestVersionAt;
  if (post.status === 'published') return scheduled.publishedAt ?? scheduled.publishAt;
  return scheduled.publishAt;
}

/** The three lines of a row's time column: Tomorrow, Oct 12, 9:00 AM. */
export function rowWhen(iso: string, now: Date = new Date()) {
  const then = new Date(iso);
  return { day: relativeDay(then, now), date: date.format(then), time: time.format(then) };
}
