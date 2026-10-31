import type { OfferedAllowance, OfferedTrial } from '@/services/billingService';
import type { AllowanceTopic } from './AllowanceInfo';
import { count, generationsAndXPosts } from './counts';

export interface OfferLine {
  text: string;
  info?: AllowanceTopic;
}

function withLinks(links: number, phrase: (n: number) => string): string {
  return links === 0 ? 'none with a link' : phrase(links);
}

/** The trial's limits after its length, e.g. "7-day free trial: 125 generations and 25 X posts, up to 2 with a link." */
export function trialLine(trial: OfferedTrial): string {
  let limits = generationsAndXPosts(trial.generations, trial.xPosts);
  if (trial.xPosts !== null && trial.linkXPosts !== null) {
    limits += `, ${withLinks(trial.linkXPosts, (n) => `up to ${n} with a link`)}`;
  }
  return limits ? `${trial.days}-day free trial: ${limits}.` : `${trial.days}-day free trial.`;
}

/**
 * What a Plan gets a User, from the Instance's caps: a line whose cap is empty is left out.
 * `trial` is the Trial this visitor would start with, or null for none.
 */
export function offerLines(allowance: OfferedAllowance, trial: OfferedTrial | null): OfferLine[] {
  const lines: OfferLine[] = [];
  if (allowance.generations !== null) {
    lines.push({
      text: `${count(allowance.generations, 'post generation', 'post generations')} a month.`,
      info: 'generations',
    });
  }
  if (allowance.xPosts !== null) {
    const links =
      allowance.linkXPosts === null
        ? ''
        : `, ${withLinks(allowance.linkXPosts, (n) => `up to ${n} of them with a link`)}`;
    lines.push({
      text: `Publish ${count(allowance.xPosts, 'X post', 'X posts')} a month${links}.`,
      info: 'xPosts',
    });
  }
  lines.push({ text: 'Write in the voice of your favorite X creators.' });
  if (trial) lines.push({ text: trialLine(trial) });
  return lines;
}
