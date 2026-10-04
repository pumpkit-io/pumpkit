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

const PRICES = {
  data: [
    {
      id: 'price_m',
      currency: 'eur',
      unit_amount: 900,
      recurring: { interval: 'month', interval_count: 1 },
      product: { id: 'prod_1', name: 'Pro', description: null },
    },
  ],
};

/** Fakes the backend at the axios adapter and records every request as "METHOD url". */
function fakeBackend(subscription: object) {
  const requests: string[] = [];
  const routes: Record<string, unknown> = {
    'GET /stripe/me': subscription,
    'GET /stripe/prices': PRICES,
    'POST /stripe/checkout': { url: 'https://checkout.stripe.test/s', session_id: 'cs_1' },
    'POST /stripe/billing-portal': { url: 'https://portal.stripe.test/x' },
  };
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const key = `${(config.method ?? 'get').toUpperCase()} ${config.url}`;
    requests.push(key);
    if (!(key in routes)) {
      return { data: { detail: 'Not Found' }, status: 404, statusText: '', headers: {}, config };
    }
    return { data: routes[key], status: 200, statusText: 'OK', headers: {}, config };
  };
  return { requests };
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
    expect(screen.getByText(/no active subscription/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /subscribe to pro/i })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
      'Subscription',
    ]);
    expect(backend.requests.sort()).toEqual(['GET /stripe/me', 'GET /stripe/prices']);
  });

  it('starts a Subscription checkout when Subscribe is clicked', async () => {
    const backend = fakeBackend(NO_SUBSCRIPTION);
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /subscribe to pro/i }));
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://checkout.stripe.test/s'));
    expect(backend.requests).toContain('POST /stripe/checkout');
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
