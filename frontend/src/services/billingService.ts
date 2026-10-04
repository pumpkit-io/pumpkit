import { apiService } from './apiService';

export interface SubscriptionView {
  status: string | null;
  stripePriceId: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  isActive: boolean;
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

interface SubscriptionMeApi {
  status: string | null;
  stripe_price_id: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  is_active: boolean;
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
  fetchSubscription: async (): Promise<SubscriptionView> => {
    const { data } = await apiService.get<SubscriptionMeApi>('/stripe/me');
    return {
      status: data.status,
      stripePriceId: data.stripe_price_id,
      currentPeriodEnd: data.current_period_end,
      cancelAtPeriodEnd: data.cancel_at_period_end,
      isActive: data.is_active,
    };
  },

  fetchPlans: async (): Promise<Plan[]> => {
    const { data } = await apiService.get<{ data: PlanApi[] }>('/stripe/plans');
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
    const { data } = await apiService.post<{ url: string }>('/stripe/checkout', {
      plan_key: planKey,
    });
    return data.url;
  },

  openBillingPortal: async (): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/stripe/billing-portal');
    return data.url;
  },
};

export function errorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}
