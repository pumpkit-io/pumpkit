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
  /** The Trial a Checkout would start with; set only when the User may subscribe. */
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

  fetchPlans: async (): Promise<Plan[]> => {
    const { data } = await apiService.get<{ data: PlanApi[] }>('/billing/plans');
    return data.data.map((p) => ({
      key: p.key,
      productName: p.product_name,
      amount: p.amount,
      currency: p.currency,
      interval: p.interval,
      intervalCount: p.interval_count,
    }));
  },

  /** Starts Checkout for a Plan; the server decides the price, quantity and any Trial. */
  startSubscriptionCheckout: async (planKey: string): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/billing/checkout', {
      plan_key: planKey,
    });
    return data.url;
  },

  openBillingPortal: async (): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/billing/portal');
    return data.url;
  },
};

export function errorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}
