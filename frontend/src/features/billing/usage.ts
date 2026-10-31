import type { AllowanceUsage, UsageCount } from '@/services/usageService';

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

const TOP_UP_LEFT = {
  generations: 'generationsLeft',
  xPosts: 'xPostsLeft',
  linkXPosts: 'linkXPostsLeft',
} as const;

/** What the User's Top-ups have left together of a count, spent once the Allowance is used up. */
export function leftInTopUps(allowance: AllowanceUsage, count: keyof typeof TOP_UP_LEFT): number {
  return allowance.topUps.reduce((sum, topUp) => sum + topUp[TOP_UP_LEFT[count]], 0);
}
