import type { PlanCatalogState } from '@/components/blocks/use-plan-catalog';

/** Null labels reserve space while the catalogue loads, avoiding a flash of the wrong offer. */
export interface CtaLabels {
  hero: string | null;
  nav: string | null;
  note: string | null;
}

const NEUTRAL: CtaLabels = { hero: 'Get started', nav: 'Get started', note: null };

/** Trial copy appears only when the catalogue offers it. */
export function ctaLabels(state: PlanCatalogState, sellsPlans: boolean): CtaLabels {
  if (!sellsPlans || state.status === 'error') return NEUTRAL;
  if (state.status === 'loading') return { hero: null, nav: null, note: null };
  const { trial, plans } = state.catalog;
  if (!trial || plans.length === 0) return NEUTRAL;
  return { hero: 'Start free trial', nav: 'Start trial', note: `${trial.days}-day free trial` };
}
