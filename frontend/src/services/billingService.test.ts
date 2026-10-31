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

describe('billingService.startTopUpCheckout', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends only the acceptance: the server decides the price and the pack', async () => {
    const post = vi
      .spyOn(apiService, 'post')
      .mockResolvedValue({ data: { url: 'https://checkout.stripe.test/t' } } as never);

    const url = await billingService.startTopUpCheckout('2026-10-11', {
      acceptedTerms: true,
      requestedImmediateStart: true,
      approvedSpecificClauses: true,
    });

    expect(url).toBe('https://checkout.stripe.test/t');
    expect(post).toHaveBeenCalledWith('/billing/top-ups/checkout', {
      terms_version: '2026-10-11',
      accepted_terms: true,
      requested_immediate_start: true,
      approved_specific_clauses: true,
    });
  });

  it('sends no acceptance where the Instance has no Terms', async () => {
    const post = vi
      .spyOn(apiService, 'post')
      .mockResolvedValue({ data: { url: 'https://checkout.stripe.test/t' } } as never);

    await billingService.startTopUpCheckout(null, {
      acceptedTerms: false,
      requestedImmediateStart: false,
      approvedSpecificClauses: false,
    });

    expect(post).toHaveBeenCalledWith('/billing/top-ups/checkout', {});
  });
});
