import type { DesiredAction, Format, Funnel, Plan } from '@/services/postService';

const BUILT_FOR: Record<Funnel, string> = {
  top: 'Built for reach',
  middle: 'Built for trust',
  bottom: 'Built for conversion',
};

const AIMS_FOR: Record<DesiredAction, string> = {
  dwell_time: 'aims for full reads',
  reply: 'aims for replies',
  bookmark: 'aims for bookmarks',
  repost: 'aims for reposts',
  share: 'aims for shares',
  follow: 'aims for follows',
  trust: 'aims for trust',
  click: 'aims for clicks',
  DM: 'aims for DMs',
  'sign-up': 'aims for sign-ups',
  buy: 'aims for sales',
};

/**
 * The Plan in plain words: "Built for trust · aims for bookmarks · medium". The Length is left
 * out of a Thread, which has none.
 */
export function planLine(plan: Plan, format: Format): string {
  const length = format === 'thread' ? null : plan.length;
  return [BUILT_FOR[plan.funnel], AIMS_FOR[plan.desiredAction], ...(length ? [length] : [])].join(
    ' · ',
  );
}
