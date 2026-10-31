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

/** What each Allowance period allows; a null cap is no cap. */
export interface OfferedAllowance {
  generations: number | null;
  xPosts: number | null;
  linkXPosts: number | null;
}

/** The Trial a first Subscription starts with, and its own Allowance. */
export interface OfferedTrial extends OfferedAllowance {
  days: number;
}

/** The Top-up a paid-up User may buy: its price in minor units and what it adds. */
export interface TopUpOffer extends OfferedAllowance {
  amount: number;
  currency: string;
}

/** The Plans on sale, what they allow, and the Terms version a checkout must accept. */
export interface PlanCatalog {
  plans: Plan[];
  /** The current Terms' "Last updated" date, in ISO form; null where the Instance has no Terms (ADR 0011). */
  termsVersion: string | null;
  allowance: OfferedAllowance;
  /** Null where the Instance offers no Trial; whether this User gets one is `BillingMe.trialDays`. */
  trial: OfferedTrial | null;
  /** Null where the Instance sells no Top-ups; whether this User may buy one is in usage. */
  topUp: TopUpOffer | null;
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

interface OfferedAllowanceApi {
  generations: number | null;
  x_posts: number | null;
  link_x_posts: number | null;
}

interface PlansApi {
  data: PlanApi[];
  terms_version: string | null;
  allowance: OfferedAllowanceApi;
  trial: (OfferedAllowanceApi & { days: number }) | null;
  top_up: (OfferedAllowanceApi & { amount: number; currency: string }) | null;
}

function offeredAllowance(a: OfferedAllowanceApi): OfferedAllowance {
  return { generations: a.generations, xPosts: a.x_posts, linkXPosts: a.link_x_posts };
}

function termsFields(termsVersion: string | null, acceptance: TermsAcceptance) {
  return termsVersion
    ? {
        terms_version: termsVersion,
        accepted_terms: acceptance.acceptedTerms,
        requested_immediate_start: acceptance.requestedImmediateStart,
        approved_specific_clauses: acceptance.approvedSpecificClauses,
      }
    : {};
}

function billingMe(data: BillingMeApi): BillingMe {
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
}

export const billingService = {
  fetchBillingMe: async (): Promise<BillingMe> => {
    const { data } = await apiService.get<BillingMeApi>('/billing/me');
    return billingMe(data);
  },

  fetchPlans: async (): Promise<PlanCatalog> => {
    const { data } = await apiService.get<PlansApi>('/billing/plans');
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
      allowance: offeredAllowance(data.allowance),
      trial: data.trial && { days: data.trial.days, ...offeredAllowance(data.trial) },
      topUp: data.top_up
        ? {
            amount: data.top_up.amount,
            currency: data.top_up.currency,
            ...offeredAllowance(data.top_up),
          }
        : null,
    };
  },

  /**
   * Starts Stripe Checkout for a Plan with the User's acceptance of `termsVersion` (ADR 0010),
   * or with the Plan alone when `termsVersion` is null because the Instance has no Terms.
   * The server decides the price, quantity and any Trial, refuses an acceptance missing a box,
   * and refuses with a 409 when `termsVersion` is no longer current.
   */
  startSubscriptionCheckout: async (
    planKey: string,
    termsVersion: string | null,
    acceptance: TermsAcceptance,
  ): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/billing/checkout', {
      plan_key: planKey,
      ...termsFields(termsVersion, acceptance),
    });
    return data.url;
  },

  /**
   * Starts Stripe Checkout for one Top-up, with the same acceptance of the Terms as a
   * Subscription's (ADR 0010). The server refuses with a 409 unless the User is paid up.
   */
  startTopUpCheckout: async (
    termsVersion: string | null,
    acceptance: TermsAcceptance,
  ): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>(
      '/billing/top-ups/checkout',
      termsFields(termsVersion, acceptance),
    );
    return data.url;
  },

  /**
   * Ends the User's Trial now, so the first period is charged today and the monthly Allowance
   * starts at once. A failed charge rejects with the backend's message (a 402).
   */
  subscribeNow: async (): Promise<BillingMe> => {
    const { data } = await apiService.post<BillingMeApi>('/billing/subscribe-now');
    return billingMe(data);
  },

  openBillingPortal: async (): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/billing/portal');
    return data.url;
  },
};
