import type { AllowanceUsage, UsageCount } from '@/services/usageService';

/** Under this share of a count left, the User is warned at the action and its bar turns. */
export const LOW_SHARE = 0.1;

/**
 * A day in UTC, where periods turn, such as "14 November", with the year for a Top-up's expiry,
 * which is up to 12 months away.
 */
export function allowanceDay(moment: Date, { withYear = false } = {}): string {
  return moment.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: withYear ? 'numeric' : undefined,
    timeZone: 'UTC',
  });
}

function ordinal(day: number): string {
  const suffix =
    day % 10 === 1 && day !== 11
      ? 'st'
      : day % 10 === 2 && day !== 12
        ? 'nd'
        : day % 10 === 3 && day !== 13
          ? 'rd'
          : 'th';
  return `${day}${suffix}`;
}

/** When paid periods reset, such as "Resets on the 14th of each month". */
export function resetsLine(day: number): string {
  // Every month has the 28th; from the 29th on, a shorter month resets on its last day.
  const shorter = day > 28 ? ', or the last day of shorter months' : '';
  return `Resets on the ${ordinal(day)} of each month${shorter}`;
}

/** Whether less than `LOW_SHARE` of a capped count is left. */
export function isLow({ limit, left }: UsageCount): boolean {
  return limit !== null && left !== null && left < limit * LOW_SHARE;
}

const TOP_UP_LEFT = {
  generations: 'generationsLeft',
  xPosts: 'xPostsLeft',
  linkXPosts: 'linkXPostsLeft',
} as const;

/** What the User's Top-ups have left together of a count, spent once the Allowance is used up. */
export function leftInTopUps(allowance: AllowanceUsage, count: keyof typeof TOP_UP_LEFT): number {
  return allowance.topUps.reduce((sum, topUp) => sum + topUp[TOP_UP_LEFT[count]], 0);
}
