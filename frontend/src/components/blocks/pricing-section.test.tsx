import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/services/billingService', () => ({ billingService: { fetchPrices: vi.fn() } }));
import { billingService } from '@/services/billingService';
import { PricingSection } from './pricing-section';

const renderSection = () =>
  render(
    <MemoryRouter>
      <PricingSection />
    </MemoryRouter>,
  );

describe('PricingSection', () => {
  it('lists recurring prices from Stripe', async () => {
    vi.mocked(billingService.fetchPrices).mockResolvedValue([
      {
        id: 'price_m',
        currency: 'eur',
        unitAmount: 900,
        recurring: { interval: 'month', intervalCount: 1 },
        product: { id: 'p', name: 'Pro', description: 'For teams' },
      },
      {
        id: 'price_once',
        currency: 'eur',
        unitAmount: 500,
        recurring: null,
        product: { id: 'q', name: 'One-off', description: null },
      },
    ]);
    renderSection();
    expect(await screen.findByText('Pro')).toBeInTheDocument();
    expect(screen.queryByText('One-off')).not.toBeInTheDocument();
  });

  it('shows a fallback when pricing cannot load', async () => {
    vi.mocked(billingService.fetchPrices).mockRejectedValue(new Error('down'));
    renderSection();
    expect(await screen.findByText(/pricing is coming soon/i)).toBeInTheDocument();
  });
});
