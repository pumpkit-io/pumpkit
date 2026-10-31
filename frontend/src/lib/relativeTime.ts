const UNITS: [Intl.RelativeTimeFormatUnit, string, number][] = [
  ['year', 'y', 365 * 24 * 60 * 60],
  ['month', 'mo', 30 * 24 * 60 * 60],
  ['week', 'w', 7 * 24 * 60 * 60],
  ['day', 'd', 24 * 60 * 60],
  ['hour', 'h', 60 * 60],
  ['minute', 'm', 60],
];

const format = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

const timeFormat = new Intl.DateTimeFormat('en', { hour: 'numeric', minute: '2-digit' });

/** The local time of day of `date`: "3:42 PM". */
export function timeOfDay(date: Date): string {
  return timeFormat.format(date);
}

const dayFormat = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' });

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** The local day and time of `date`: "today at 3:42 PM", "tomorrow at 3:42 PM", "Oct 9 at 3:42 PM". */
export function dayAndTime(date: Date, now: Date = new Date()): string {
  const days = Math.round((startOfDay(date) - startOfDay(now)) / (24 * 60 * 60 * 1000));
  const day = days === 0 ? 'today' : days === 1 ? 'tomorrow' : dayFormat.format(date);
  return `${day} at ${timeOfDay(date)}`;
}

function secondsSince(iso: string, now: Date): number {
  // A clock running slightly behind the server's reads as "just now", not "in 10 seconds".
  return Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
}

/** How long ago `iso` was, in the largest whole unit: "2 hours ago", "yesterday", "just now". */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const seconds = secondsSince(iso, now);
  for (const [unit, , size] of UNITS) {
    if (seconds >= size) return format.format(-Math.floor(seconds / size), unit);
  }
  return 'just now';
}

/** `timeAgo` for tight spaces: "2h ago", "now". */
export function shortTimeAgo(iso: string, now: Date = new Date()): string {
  const seconds = secondsSince(iso, now);
  for (const [, suffix, size] of UNITS) {
    if (seconds >= size) return `${Math.floor(seconds / size)}${suffix} ago`;
  }
  return 'now';
}
