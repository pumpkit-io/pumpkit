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

const NO_SUBSCRIPTION = {
  status: null,
  stripe_price_id: null,
  current_period_end: null,
  cancel_at_period_end: false,
  is_active: false,
};

const ACTIVE_SUBSCRIPTION = {
  status: 'active',
  stripe_price_id: 'price_m',
  current_period_end: '2030-01-01T00:00:00Z',
  cancel_at_period_end: false,
  is_active: true,
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
function fakeBackend(subscription: object) {
  const requests: string[] = [];
  const bodies: Record<string, unknown> = {};
  const routes: Record<string, unknown> = {
    'GET /billing/me': subscription,
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

  it('renders the Subscription state and nothing but the Subscription', async () => {
    const backend = fakeBackend(NO_SUBSCRIPTION);
    renderDialog();

    expect(await screen.findByText('Pro')).toBeInTheDocument();
    expect(screen.getByText('Pro yearly')).toBeInTheDocument();
    expect(screen.getByText(/€9\.00 \/ month/)).toBeInTheDocument();
    expect(screen.getByText(/no active subscription/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Subscription',
    ]);
    expect(backend.requests.sort()).toEqual(['GET /billing/me', 'GET /billing/plans']);
  });

  it('starts Checkout with only the chosen Plan key when Subscribe is clicked', async () => {
    const backend = fakeBackend(NO_SUBSCRIPTION);
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /subscribe to pro yearly/i }));
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://checkout.stripe.test/s'));
    expect(backend.bodies['POST /billing/checkout']).toEqual({ plan_key: 'pumpkit_pro_yearly' });
  });

  it('shows Manage for an active Subscription', async () => {
    fakeBackend(ACTIVE_SUBSCRIPTION);
    renderDialog();
    expect(await screen.findByRole('button', { name: /manage subscription/i })).toBeInTheDocument();
  });

  it('opens the billing portal in the current tab via redirectTo', async () => {
    fakeBackend(ACTIVE_SUBSCRIPTION);
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /manage subscription/i }));
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'));
  });
});
