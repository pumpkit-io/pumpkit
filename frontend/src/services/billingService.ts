import { apiService } from './apiService';

export interface SubscriptionView {
  status: string | null;
  stripePriceId: string | null;
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  isActive: boolean;
}

export interface Price {
  id: string;
  currency: string;
  unitAmount: number | null;
  recurring: { interval: string; intervalCount: number } | null;
  product: { id: string; name: string | null; description: string | null } | null;
}

export interface Product {
  id: string;
  name: string;
  description: string;
  amountCents: number;
  currency: string;
}

export interface Purchase {
  id: string;
  productId: string;
  status: 'pending' | 'paid' | 'refunded' | 'partially_refunded' | 'disputed' | 'failed';
  currency: string;
  amountSubtotalCents: number;
  amountTotalCents: number | null;
  refundedAmountCents: number;
  createdAt: string;
}

interface SubscriptionMeApi {
  status: string | null;
  stripe_price_id: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  is_active: boolean;
}

interface PriceApi {
  id: string;
  currency: string;
  unit_amount: number | null;
  recurring: { interval: string; interval_count: number } | null;
  product: { id: string; name: string | null; description: string | null } | null;
}

interface ProductApi {
  id: string;
  name: string;
  description: string;
  amount_cents: number;
  currency: string;
}

interface PurchaseApi {
  id: string;
  product_id: string;
  status: Purchase['status'];
  currency: string;
  amount_subtotal_cents: number;
  amount_total_cents: number | null;
  refunded_amount_cents: number;
  created_at: string;
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

  fetchPrices: async (): Promise<Price[]> => {
    const { data } = await apiService.get<{ data: PriceApi[] }>('/stripe/prices');
    return data.data.map((p) => ({
      id: p.id,
      currency: p.currency,
      unitAmount: p.unit_amount,
      recurring: p.recurring ? { interval: p.recurring.interval, intervalCount: p.recurring.interval_count } : null,
      product: p.product,
    }));
  },

  startSubscriptionCheckout: async (priceId: string): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/stripe/checkout', { price_id: priceId });
    return data.url;
  },

  openBillingPortal: async (): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/stripe/billing-portal');
    return data.url;
  },

  fetchProducts: async (): Promise<Product[]> => {
    const { data } = await apiService.get<{ data: ProductApi[] }>('/billing/products');
    return data.data.map((p) => ({
      id: p.id,
      name: p.name,
      description: p.description,
      amountCents: p.amount_cents,
      currency: p.currency,
    }));
  },

  startPurchaseCheckout: async (productId: string): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/billing/purchases/checkout', {
      product_id: productId,
    });
    return data.url;
  },

  fetchPurchases: async (): Promise<Purchase[]> => {
    const { data } = await apiService.get<{ data: PurchaseApi[] }>('/billing/purchases');
    return data.data.map((p) => ({
      id: p.id,
      productId: p.product_id,
      status: p.status,
      currency: p.currency,
      amountSubtotalCents: p.amount_subtotal_cents,
      amountTotalCents: p.amount_total_cents,
      refundedAmountCents: p.refunded_amount_cents,
      createdAt: p.created_at,
    }));
  },
};

export function errorMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}
