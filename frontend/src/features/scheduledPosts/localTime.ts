/** The browser's timezone, which every date and time picker works in. */
export const TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** A local time as a datetime-local input writes it: 2026-10-12T09:00. */
export function localInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The earliest time the backend accepts, as a datetime-local input's `min`. */
export function earliestInputValue(): string {
  return localInputValue(new Date(Date.now() + 60_000));
}
