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

describe('future paid signup', () => {
  afterEach(() => vi.restoreAllMocks());

  it('reads the exact server offer and sends separate paid consent with its stable operation', async () => {
    const post = vi
      .spyOn(apiService, 'post')
      .mockResolvedValueOnce({
        data: {
          plan_key: 'configured_year',
          product_name: 'Configured plan',
          amount: 12000,
          currency: 'eur',
          interval: 'year',
          interval_count: 1,
          first_payment_at: '2028-03-31T12:00:00Z',
          terms_version: '2026-11-08',
          revision: 'signed-offer',
        },
      } as never)
      .mockResolvedValueOnce({
        data: {
          operation_id: '550e8400-e29b-41d4-a716-446655440000',
          status: 'pending',
          detail: null,
          url: 'https://checkout.test/setup',
          session_id: 'cs_setup',
          first_payment_at: '2028-03-31T12:00:00Z',
          plan_key: 'configured_year',
        },
      } as never);
    const offer = await billingService.previewPaidSignup('configured_year');
    expect(offer).toEqual({
      planKey: 'configured_year',
      productName: 'Configured plan',
      amount: 12000,
      currency: 'eur',
      interval: 'year',
      intervalCount: 1,
      firstPaymentAt: '2028-03-31T12:00:00Z',
      termsVersion: '2026-11-08',
      revision: 'signed-offer',
    });
    const result = await billingService.createPaidSignup({
      operationId: '550e8400-e29b-41d4-a716-446655440000',
      revision: offer.revision,
      termsVersion: offer.termsVersion,
      acceptedTerms: true,
      requestedImmediateStart: true,
      approvedSpecificClauses: true,
      language: 'en',
    });
    expect(post).toHaveBeenNthCalledWith(1, '/billing/paid-signups/preview', {
      plan_key: 'configured_year',
    });
    expect(post).toHaveBeenNthCalledWith(2, '/billing/paid-signups', {
      operation_id: '550e8400-e29b-41d4-a716-446655440000',
      revision: 'signed-offer',
      terms_version: '2026-11-08',
      accepted_terms: true,
      requested_immediate_start: true,
      approved_specific_clauses: true,
      language: 'en',
    });
    expect(result).toEqual({
      operationId: '550e8400-e29b-41d4-a716-446655440000',
      status: 'pending',
      detail: null,
      url: 'https://checkout.test/setup',
      sessionId: 'cs_setup',
      firstPaymentAt: '2028-03-31T12:00:00Z',
      planKey: 'configured_year',
    });
  });

  it('sends no legal evidence without Terms and recovers or cancels only the named operation', async () => {
    const response = {
      data: {
        operation_id: 'operation',
        status: 'refused',
        detail: 'Review the current payment date.',
        url: null,
        session_id: null,
        first_payment_at: '2028-03-31T12:00:00Z',
        plan_key: 'configured_month',
      },
    };
    const post = vi.spyOn(apiService, 'post').mockResolvedValue(response as never);
    const get = vi.spyOn(apiService, 'get').mockResolvedValue(response as never);
    await billingService.createPaidSignup({
      operationId: 'operation',
      revision: 'revision',
      termsVersion: null,
      acceptedTerms: false,
      requestedImmediateStart: false,
      approvedSpecificClauses: false,
      language: 'en',
    });
    expect(post).toHaveBeenCalledWith('/billing/paid-signups', {
      operation_id: 'operation',
      revision: 'revision',
      language: 'en',
    });
    expect((await billingService.fetchPaidSignup('operation')).status).toBe('refused');
    expect(get).toHaveBeenCalledWith('/billing/paid-signups/operation');
    await billingService.cancelPaidSignup('operation');
    expect(post).toHaveBeenCalledWith('/billing/paid-signups/operation/cancel');
  });
});
