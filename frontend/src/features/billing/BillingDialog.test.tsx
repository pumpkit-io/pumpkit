import type { InternalAxiosRequestConfig } from 'axios';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/navigation', () => ({ redirectTo: vi.fn(), hardRedirect: vi.fn() }));

import { api } from '@/services/apiService';
import { redirectTo } from '@/lib/navigation';
import { BillingProvider } from './BillingProvider';
import { BillingDialog } from './BillingDialog';
import { useBilling } from './useBilling';

const originalAdapter = api.defaults.adapter;

const PAYMENT_FAILED = 'Your last payment failed. Update your card to keep access.';
const PERIOD_END = '2030-01-01T00:00:00Z';
const PERIOD_END_LABEL = new Date(PERIOD_END).toLocaleDateString();

/** The backend's `/billing/me` answer for a User holding a Running Subscription. */
function holding(status: string, subscribed: boolean, cancelAtPeriodEnd = false) {
  return {
    subscription: {
      status,
      plan_key: 'pumpkit_pro_monthly',
      current_period_end: PERIOD_END,
      cancel_at_period_end: cancelAtPeriodEnd,
    },
    subscribed,
    may_subscribe: false,
    trial_days: null,
  };
}

const MAY_SUBSCRIBE_WITH_TRIAL = {
  subscription: null,
  subscribed: false,
  may_subscribe: true,
  trial_days: 14,
};

const MAY_SUBSCRIBE_WITHOUT_TRIAL = { ...MAY_SUBSCRIBE_WITH_TRIAL, trial_days: null };

const INCOMPLETE = {
  subscription: {
    status: 'incomplete',
    plan_key: 'pumpkit_pro_monthly',
    current_period_end: PERIOD_END,
    cancel_at_period_end: false,
  },
  subscribed: false,
  may_subscribe: true,
  trial_days: null,
};

const PLANS = {
  data: [
    {
      key: 'pumpkit_pro_monthly',
      product_name: 'Pro',
      amount: 900,
      currency: 'eur',
      interval: 'month',
      interval_count: 1,
    },
    {
      key: 'pumpkit_pro_yearly',
      product_name: 'Pro yearly',
      amount: 9000,
      currency: 'eur',
      interval: 'year',
      interval_count: 1,
    },
  ],
};

/**
 * Fakes the backend at the axios adapter. Records every request as "METHOD url"
 * and the JSON body of each request that has one.
 */
function fakeBackend(me: object) {
  const requests: string[] = [];
  const bodies: Record<string, unknown> = {};
  const routes: Record<string, unknown> = {
    'GET /billing/me': me,
    'GET /billing/plans': PLANS,
    'POST /billing/checkout': { url: 'https://checkout.stripe.test/s', session_id: 'cs_1' },
    'POST /billing/portal': { url: 'https://portal.stripe.test/x' },
  };
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const key = `${(config.method ?? 'get').toUpperCase()} ${config.url}`;
    requests.push(key);
    if (config.data) bodies[key] = JSON.parse(config.data as string);
    if (!(key in routes)) {
      return { data: { detail: 'Not Found' }, status: 404, statusText: '', headers: {}, config };
    }
    return { data: routes[key], status: 200, statusText: 'OK', headers: {}, config };
  };
  return { requests, bodies };
}

function OpenOnMount() {
  const { open } = useBilling();
  useEffect(() => open('test'), [open]);
  return null;
}

function renderDialog() {
  return render(
    <BillingProvider>
      <OpenOnMount />
      <BillingDialog />
    </BillingProvider>,
  );
}

describe('BillingDialog', () => {
  beforeEach(() => vi.mocked(redirectTo).mockClear());
  afterEach(() => {
    api.defaults.adapter = originalAdapter;
  });

  it('offers the Plans, each with the free Trial, when the User may subscribe with one', async () => {
    const backend = fakeBackend(MAY_SUBSCRIBE_WITH_TRIAL);
    renderDialog();

    expect(await screen.findByText('Pro')).toBeInTheDocument();
    expect(screen.getByText('Pro yearly')).toBeInTheDocument();
    expect(screen.getByText(/€9\.00 \/ month/)).toBeInTheDocument();
    expect(screen.getAllByText('14-day free Trial')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /manage subscription/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Subscription',
    ]);
    expect(backend.requests.sort()).toEqual(['GET /billing/me', 'GET /billing/plans']);
  });

  it('offers the Plans without a Trial when the User gets none', async () => {
    fakeBackend(MAY_SUBSCRIBE_WITHOUT_TRIAL);
    renderDialog();

    expect(await screen.findByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
    expect(screen.queryByText(/free Trial/)).not.toBeInTheDocument();
  });

  it('offers the Plans to a User whose Subscription is still incomplete', async () => {
    fakeBackend(INCOMPLETE);
    renderDialog();

    expect(await screen.findByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /manage subscription/i })).not.toBeInTheDocument();
    expect(screen.queryByText(PAYMENT_FAILED)).not.toBeInTheDocument();
  });

  it('starts Checkout with only the chosen Plan key when Subscribe is clicked', async () => {
    const backend = fakeBackend(MAY_SUBSCRIBE_WITH_TRIAL);
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /subscribe to pro yearly/i }));
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://checkout.stripe.test/s'));
    expect(backend.bodies['POST /billing/checkout']).toEqual({ plan_key: 'pumpkit_pro_yearly' });
  });

  it.each(['trialing', 'active'])(
    'shows a %s Subscription, its renewal date and Manage, and no Plans',
    async (status) => {
      fakeBackend(holding(status, true));
      renderDialog();

      expect(
        await screen.findByRole('button', { name: 'Manage subscription' }),
      ).toBeInTheDocument();
      expect(screen.getByText(status)).toBeInTheDocument();
      expect(screen.getByText(new RegExp(`renews ${PERIOD_END_LABEL}`))).toBeInTheDocument();
      expect(screen.queryByText(PAYMENT_FAILED)).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^subscribe to/i })).not.toBeInTheDocument();
    },
  );

  it('shows when a Subscription set to cancel ends', async () => {
    fakeBackend(holding('active', true, true));
    renderDialog();

    expect(await screen.findByText(new RegExp(`ends ${PERIOD_END_LABEL}`))).toBeInTheDocument();
  });

  it.each([
    ['past_due', true],
    ['unpaid', false],
    ['paused', false],
  ])(
    'warns that the last payment of a %s Subscription failed and offers Fix payment',
    async (status, subscribed) => {
      fakeBackend(holding(status, subscribed));
      renderDialog();

      expect(await screen.findByText(PAYMENT_FAILED)).toBeInTheDocument();
      expect(screen.getByText(status)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Fix payment' })).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /manage subscription/i }),
      ).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^subscribe to/i })).not.toBeInTheDocument();
    },
  );

  it.each([
    ['Manage subscription', holding('active', true)],
    ['Fix payment', holding('past_due', true)],
  ])('opens the billing portal in the current tab from %s', async (label, me) => {
    fakeBackend(me);
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: label }));
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'));
  });

  it.each([
    ['may subscribe', MAY_SUBSCRIBE_WITH_TRIAL, 'Subscribe to Pro'],
    ['has a Running Subscription', holding('active', true), 'Manage subscription'],
    ['is behind on payment', holding('unpaid', false), 'Fix payment'],
  ])('keeps Payments & invoices in the footer when the User %s', async (_, me, loadedButton) => {
    fakeBackend(me);
    renderDialog();
    await screen.findByRole('button', { name: loadedButton });
    fireEvent.click(screen.getByRole('button', { name: /payments & invoices/i }));
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'));
  });
});
