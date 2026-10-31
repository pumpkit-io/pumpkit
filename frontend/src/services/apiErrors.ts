/** The backend's `detail` when it is a sentence for the User, else `fallback`. */
export function errorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  // An HTTP client's own message ("Network Error") is no sentence for the User.
  const fromHttpClient = (e as { isAxiosError?: unknown })?.isAxiosError === true;
  if (e instanceof Error && e.message && !fromHttpClient) return e.message;
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

/** What an Allowance counts. */
export type AllowanceCount = 'generations' | 'x_posts' | 'link_x_posts';
/** What a User at a limit can do before the Allowance period resets. */
export type AllowanceWayOut = 'top_up' | 'subscribe_now' | 'update_payment';

/** The backend's refusal of an action that needs more of the User's Allowance than is left. */
export interface AllowanceUsedUp {
  message: string;
  ranOut: AllowanceCount;
  needed: number;
  left: number;
  resetsAt: Date;
  wayOut: AllowanceWayOut | null;
}

/** The Allowance refusal a request failed with (a 409 with code `ALLOWANCE_USED_UP`), else null. */
export function errorAllowanceUsedUp(e: unknown): AllowanceUsedUp | null {
  if (errorStatus(e) !== 409) return null;
  const data = (e as { response?: { data?: Record<string, unknown> } }).response?.data;
  if (!data || data.code !== 'ALLOWANCE_USED_UP' || typeof data.detail !== 'string') return null;
  return {
    message: data.detail,
    ranOut: data.ran_out as AllowanceCount,
    needed: Number(data.needed),
    left: Number(data.left),
    resetsAt: new Date(String(data.resets_at)),
    wayOut: (data.way_out as AllowanceWayOut | null | undefined) ?? null,
  };
}

/** The provider's page to authenticate a payment on, when a request failed waiting for that. */
export function errorPaymentAuthenticationUrl(e: unknown): string | null {
  const data = (e as { response?: { data?: Record<string, unknown> } })?.response?.data;
  if (data?.code !== 'PAYMENT_NEEDS_AUTHENTICATION' || typeof data.url !== 'string') return null;
  return data.url;
}
