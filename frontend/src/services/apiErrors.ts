/** The backend's `detail` when it is a sentence for the User, else `fallback`. */
export function errorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

/** When a 429 says the request may be sent again (its ISO `retry_at`), else null. */
export function errorRetryAt(e: unknown): Date | null {
  if (errorStatus(e) !== 429) return null;
  const retryAt = (e as { response?: { data?: { retry_at?: unknown } } }).response?.data?.retry_at;
  if (typeof retryAt !== 'string') return null;
  const date = new Date(retryAt);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The HTTP status of a failed request, or null when it never got a response. */
export function errorStatus(e: unknown): number | null {
  const status = (e as { response?: { status?: unknown } })?.response?.status;
  return typeof status === 'number' ? status : null;
}
