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
