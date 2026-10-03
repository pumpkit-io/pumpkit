import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/billingService', () => ({
  billingService: {
    fetchSubscription: vi.fn(),
    fetchPrices: vi.fn(),
    fetchProducts: vi.fn(),
    fetchPurchases: vi.fn(),
    startSubscriptionCheckout: vi.fn(),
    startPurchaseCheckout: vi.fn(),
    openBillingPortal: vi.fn(),
  },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));
vi.mock('@/lib/navigation', () => ({ redirectTo: vi.fn(), hardRedirect: vi.fn() }));

import { billingService } from '@/services/billingService';
import { redirectTo } from '@/lib/navigation';
import { BillingProvider } from './BillingProvider';
import { BillingDialog } from './BillingDialog';
import { useBilling } from './useBilling';

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
  beforeEach(() => {
    vi.mocked(billingService.fetchSubscription).mockResolvedValue({
      status: null,
      stripePriceId: null,
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
      isActive: false,
    });
    vi.mocked(billingService.fetchPrices).mockResolvedValue([
      {
        id: 'price_m',
        currency: 'eur',
        unitAmount: 900,
        recurring: { interval: 'month', intervalCount: 1 },
        product: { id: 'prod_1', name: 'Pro', description: null },
      },
    ]);
    vi.mocked(billingService.fetchProducts).mockResolvedValue([
      {
        id: 'starter-pack',
        name: 'Starter pack',
        description: 'Placeholder',
        amountCents: 1000,
        currency: 'eur',
      },
    ]);
    vi.mocked(billingService.fetchPurchases).mockResolvedValue([]);
    vi.mocked(billingService.startPurchaseCheckout).mockResolvedValue(
      'https://checkout.stripe.test/p',
    );
    vi.mocked(billingService.startSubscriptionCheckout).mockResolvedValue(
      'https://checkout.stripe.test/s',
    );
  });

  it('renders subscription plans and one-time products', async () => {
    renderDialog();
    expect(await screen.findByText('Starter pack')).toBeInTheDocument();
    expect(screen.getByText('Pro')).toBeInTheDocument();
    expect(screen.getByText(/no active subscription/i)).toBeInTheDocument();
  });

  it('starts a purchase checkout when Buy is clicked', async () => {
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /buy starter pack/i }));
    await waitFor(() =>
      expect(billingService.startPurchaseCheckout).toHaveBeenCalledWith('starter-pack'),
    );
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://checkout.stripe.test/p'));
  });

  it('shows Manage for an active subscription', async () => {
    vi.mocked(billingService.fetchSubscription).mockResolvedValue({
      status: 'active',
      stripePriceId: 'price_m',
      currentPeriodEnd: '2030-01-01T00:00:00Z',
      cancelAtPeriodEnd: false,
      isActive: true,
    });
    renderDialog();
    expect(await screen.findByRole('button', { name: /manage subscription/i })).toBeInTheDocument();
  });

  it('opens the billing portal in the current tab via redirectTo', async () => {
    vi.mocked(billingService.fetchSubscription).mockResolvedValue({
      status: 'active',
      stripePriceId: 'price_m',
      currentPeriodEnd: '2030-01-01T00:00:00Z',
      cancelAtPeriodEnd: false,
      isActive: true,
    });
    vi.mocked(billingService.openBillingPortal).mockResolvedValue('https://portal.stripe.test/x');
    renderDialog();
    fireEvent.click(await screen.findByRole('button', { name: /manage subscription/i }));
    await waitFor(() => expect(billingService.openBillingPortal).toHaveBeenCalled());
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'));
  });
});
