import type { UsageCount } from '@/services/usageService';

/** Under this share of a count left, the User is warned at the action and its bar turns. */
export const LOW_SHARE = 0.1;

/** A day of an Allowance period, such as "14 November": periods turn in UTC, and none is a year away. */
export function allowanceDay(moment: Date): string {
  return moment.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' });
}

/** Whether less than `LOW_SHARE` of a capped count is left. */
export function isLow({ limit, left }: UsageCount): boolean {
  return limit !== null && left !== null && left < limit * LOW_SHARE;
}
