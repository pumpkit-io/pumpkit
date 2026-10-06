const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 60 * 60],
  ['month', 30 * 24 * 60 * 60],
  ['week', 7 * 24 * 60 * 60],
  ['day', 24 * 60 * 60],
  ['hour', 60 * 60],
  ['minute', 60],
];

const format = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

const timeFormat = new Intl.DateTimeFormat('en', { hour: 'numeric', minute: '2-digit' });

/** The local time of day of `date`: "3:42 PM". */
export function timeOfDay(date: Date): string {
  return timeFormat.format(date);
}

/** How long ago `iso` was, in the largest whole unit: "2 hours ago", "yesterday", "just now". */
export function timeAgo(iso: string, now: Date = new Date()): string {
  // A clock running slightly behind the server's reads as "just now", not "in 10 seconds".
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  for (const [unit, size] of UNITS) {
    if (seconds >= size) return format.format(-Math.floor(seconds / size), unit);
  }
  return 'just now';
}
