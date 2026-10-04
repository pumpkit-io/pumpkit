import type { InternalAxiosRequestConfig } from 'axios';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { api } from '@/services/apiService';
import { PricingSection } from './pricing-section';

const originalAdapter = api.defaults.adapter;

/** Fakes `GET /stripe/plans` at the axios adapter. */
function fakePlansEndpoint(status: number, data: unknown) {
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const found = config.url === '/stripe/plans';
    const response = {
      data: found ? data : { detail: 'Not Found' },
      status: found ? status : 404,
      statusText: '',
      headers: {},
      config,
    };
    if (response.status >= 400) {
      throw Object.assign(new Error(`Request failed with status ${response.status}`), {
        isAxiosError: true,
        response,
        config,
      });
    }
    return response;
  };
}

const renderSection = () =>
  render(
    <MemoryRouter>
      <PricingSection />
    </MemoryRouter>,
  );

describe('PricingSection', () => {
  afterEach(() => {
    api.defaults.adapter = originalAdapter;
  });

  it('renders the Plans from the endpoint', async () => {
    fakePlansEndpoint(200, {
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
          key: 'pumpkit_pro_quarterly',
          product_name: 'Pro quarterly',
          amount: 2400,
          currency: 'eur',
          interval: 'month',
          interval_count: 3,
        },
      ],
    });
    renderSection();
    expect(await screen.findByText('Pro')).toBeInTheDocument();
    expect(screen.getByText(/€9\.00 \/ month/)).toBeInTheDocument();
    expect(screen.getByText('Pro quarterly')).toBeInTheDocument();
    expect(screen.getByText(/€24\.00 \/ 3 months/)).toBeInTheDocument();
  });

  it('shows a fallback when the Plans cannot load', async () => {
    fakePlansEndpoint(502, { detail: 'Billing is unavailable right now.', error_id: 'e' });
    renderSection();
    expect(await screen.findByText(/pricing is coming soon/i)).toBeInTheDocument();
  });
});
