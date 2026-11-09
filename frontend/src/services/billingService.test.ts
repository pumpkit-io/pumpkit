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

describe('billingService.subscribeNow', () => {
  afterEach(() => vi.restoreAllMocks());

  it('ends the trial and answers with what the User now holds', async () => {
    const post = vi.spyOn(apiService, 'post').mockResolvedValue({
      data: {
        subscription: {
          status: 'active',
          plan_key: 'pumpkit_pro_monthly',
          current_period_end: '2026-11-10T12:00:30Z',
          cancel_at: null,
        },
        subscribed: true,
        may_subscribe: false,
        trial_days: null,
      },
    } as never);

    const me = await billingService.subscribeNow();

    expect(post).toHaveBeenCalledWith('/billing/subscribe-now');
    expect(me.subscription).toEqual({
      status: 'active',
      planKey: 'pumpkit_pro_monthly',
      currentPeriodEnd: '2026-11-10T12:00:30Z',
      cancelAt: null,
    });
  });
});

describe('cardless coupon redemption', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends the operation and two-box acceptance without a paid immediate-start waiver', async () => {
    const post = vi.spyOn(apiService, 'post').mockResolvedValue({
      data: {
        operation_id: 'op-one',
        months: 3,
        starts_at: '2028-01-31T12:01:00Z',
        ends_at: '2028-04-30T12:01:00Z',
      },
    } as never);
    const result = await billingService.redeemCoupon({
      operationId: 'op-one',
      revision: 'signed-preview',
      termsVersion: '2026-11-08',
      acceptedTerms: true,
      approvedSpecificClauses: true,
      language: 'it',
    });
    expect(post).toHaveBeenCalledWith('/billing/coupons/redemptions', {
      operation_id: 'op-one',
      revision: 'signed-preview',
      terms_version: '2026-11-08',
      accepted_terms: true,
      approved_specific_clauses: true,
      language: 'it',
    });
    expect(result).toEqual({
      operationId: 'op-one',
      months: 3,
      startsAt: '2028-01-31T12:01:00Z',
      endsAt: '2028-04-30T12:01:00Z',
    });
  });

  it('reads free access independently of a Subscription', async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        subscription: null,
        subscribed: true,
        may_subscribe: false,
        trial_days: null,
        free_access: {
          starts_at: '2028-01-31T12:01:00Z',
          ends_at: '2028-04-30T12:01:00Z',
          months: 3,
        },
      },
    } as never);
    expect(await billingService.fetchBillingMe()).toEqual({
      subscription: null,
      subscribed: true,
      maySubscribe: false,
      trialDays: null,
      freeAccess: { startsAt: '2028-01-31T12:01:00Z', endsAt: '2028-04-30T12:01:00Z', months: 3 },
    });
  });
});
