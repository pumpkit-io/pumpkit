import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { billingService } from './billingService';

describe('billingService.startSubscriptionCheckout', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends the acceptance the User gave, box by box, for the backend to check', async () => {
    const post = vi
      .spyOn(apiService, 'post')
      .mockResolvedValue({ data: { url: 'https://checkout.stripe.test/s' } } as never);

    const url = await billingService.startSubscriptionCheckout(
      'pumpkit_pro_monthly',
      '2026-10-11',
      {
        acceptedTerms: true,
        requestedImmediateStart: false,
        approvedSpecificClauses: true,
      },
    );

    expect(url).toBe('https://checkout.stripe.test/s');
    expect(post).toHaveBeenCalledWith('/billing/checkout', {
      plan_key: 'pumpkit_pro_monthly',
      terms_version: '2026-10-11',
      accepted_terms: true,
      requested_immediate_start: false,
      approved_specific_clauses: true,
    });
  });
});
