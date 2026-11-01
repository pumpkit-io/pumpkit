import type { PlanCatalogState } from '@/components/blocks/use-plan-catalog';
import { formatPrice } from '@/lib/money';

export interface CtaLabels {
  hero: string;
  nav: string;
}

const NEUTRAL: CtaLabels = { hero: 'Get started', nav: 'Get started' };

/** Names the Trial only when the Instance offers one; "$0" and the day count come from the catalogue. */
export function ctaLabels(state: PlanCatalogState): CtaLabels {
  if (state.status !== 'ready') return NEUTRAL;
  const { trial, plans } = state.catalog;
  if (!trial || plans.length === 0) return NEUTRAL;
  const free = formatPrice(0, plans[0].currency);
  return { hero: `Start a ${trial.days}-day trial for ${free}`, nav: `Start for ${free}` };
}
