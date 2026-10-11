import { apiService } from './apiService';

/** Stripe's Subscription statuses. */
export type SubscriptionStatus =
  | 'trialing'
  | 'active'
  | 'incomplete'
  | 'incomplete_expired'
  | 'past_due'
  | 'canceled'
  | 'unpaid'
  | 'paused';

/** The User's Subscription: their Running one, else an `incomplete` one. */
export interface Subscription {
  status: SubscriptionStatus;
  planKey: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
}

/** What the backend says the User holds and may do. */
export interface BillingMe {
  subscription: Subscription | null;
  subscribed: boolean;
  maySubscribe: boolean;
  /** The Trial a checkout would start with; set only when the User may subscribe. */
  trialDays: number | null;
}

/** A Plan a User can subscribe to: `amount` in minor units, every `intervalCount` `interval`s. */
export interface Plan {
  key: string;
  productName: string;
  amount: number;
  currency: string;
  interval: string;
  intervalCount: number;
}

/** The three boxes a User ticks before every checkout (ADR 0010). */
export interface TermsAcceptance {
  acceptedTerms: boolean;
  requestedImmediateStart: boolean;
  approvedSpecificClauses: boolean;
}

/** The Plans on sale and the Terms version a checkout must accept. */
export interface PlanCatalog {
  plans: Plan[];
  /** The current Terms' "Last updated" date, in ISO form. */
  termsVersion: string;
}

interface BillingMeApi {
  subscription: {
    status: SubscriptionStatus;
    plan_key: string | null;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
  } | null;
  subscribed: boolean;
  may_subscribe: boolean;
  trial_days: number | null;
}

interface PlanApi {
  key: string;
  product_name: string;
  amount: number;
  currency: string;
  interval: string;
  interval_count: number;
}

export const billingService = {
  fetchBillingMe: async (): Promise<BillingMe> => {
    const { data } = await apiService.get<BillingMeApi>('/billing/me');
    const s = data.subscription;
    return {
      subscription: s && {
        status: s.status,
        planKey: s.plan_key,
        currentPeriodEnd: s.current_period_end,
        cancelAtPeriodEnd: s.cancel_at_period_end,
      },
      subscribed: data.subscribed,
      maySubscribe: data.may_subscribe,
      trialDays: data.trial_days,
    };
  },

  fetchPlans: async (): Promise<PlanCatalog> => {
    const { data } = await apiService.get<{ data: PlanApi[]; terms_version: string }>(
      '/billing/plans',
    );
    return {
      plans: data.data.map((p) => ({
        key: p.key,
        productName: p.product_name,
        amount: p.amount,
        currency: p.currency,
        interval: p.interval,
        intervalCount: p.interval_count,
      })),
      termsVersion: data.terms_version,
    };
  },

  /**
   * Starts Stripe Checkout for a Plan with the User's acceptance of `termsVersion` (ADR 0010).
   * The server decides the price, quantity and any Trial, refuses an acceptance missing a box,
   * and refuses with a 409 when `termsVersion` is no longer current.
   */
  startSubscriptionCheckout: async (
    planKey: string,
    termsVersion: string,
    acceptance: TermsAcceptance,
  ): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/billing/checkout', {
      plan_key: planKey,
      terms_version: termsVersion,
      accepted_terms: acceptance.acceptedTerms,
      requested_immediate_start: acceptance.requestedImmediateStart,
      approved_specific_clauses: acceptance.approvedSpecificClauses,
    });
    return data.url;
  },

  openBillingPortal: async (): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/billing/portal');
    return data.url;
  },
};
