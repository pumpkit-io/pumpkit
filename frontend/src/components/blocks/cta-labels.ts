import type { PlanCatalogState } from '@/components/blocks/use-plan-catalog';
import { formatPrice } from '@/lib/money';

/** A label is null while the catalogue is still loading: the button holds its text back rather than flash "Get started". */
export interface CtaLabels {
  hero: string | null;
  nav: string | null;
}

const NEUTRAL: CtaLabels = { hero: 'Get started', nav: 'Get started' };

/** Names the Trial only when the Instance offers one; "$0" and the day count come from the catalogue. */
export function ctaLabels(state: PlanCatalogState, sellsPlans: boolean): CtaLabels {
  if (!sellsPlans || state.status === 'error') return NEUTRAL;
  if (state.status === 'loading') return { hero: null, nav: null };
  const { trial, plans } = state.catalog;
  if (!trial || plans.length === 0) return NEUTRAL;
  const free = formatPrice(0, plans[0].currency);
  return { hero: `Start a ${trial.days}-day trial for ${free}`, nav: `Start for ${free}` };
}
