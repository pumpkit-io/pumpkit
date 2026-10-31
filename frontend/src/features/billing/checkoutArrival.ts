export type CheckoutStatus = 'success' | 'cancelled';

/** What the Stripe return routes leave in the location state, for `/` and the Paywall. */
export interface CheckoutArrival {
  checkoutStatus?: CheckoutStatus;
}

export function checkoutStatusOf(state: unknown): CheckoutStatus | undefined {
  return (state as CheckoutArrival | null)?.checkoutStatus;
}
