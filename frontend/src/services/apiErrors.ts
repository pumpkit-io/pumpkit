/** The backend's `detail` when it is a sentence for the User, else `fallback`. */
export function errorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

/** The HTTP status of a failed request, or null when it never got a response. */
export function errorStatus(e: unknown): number | null {
  const status = (e as { response?: { status?: unknown } })?.response?.status;
  return typeof status === 'number' ? status : null;
}
