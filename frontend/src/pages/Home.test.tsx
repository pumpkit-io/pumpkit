import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/services/userService', () => ({
  userService: {
    fetchProfile: vi.fn().mockResolvedValue({
      id: 'user_01HZX',
      email: 'ada@example.com',
      firstName: 'Ada',
      lastName: 'Lovelace',
      avatarUrl: null,
    }),
    updateProfile: vi.fn(),
  },
}));
vi.mock('@/services/billingService', () => ({
  billingService: {
    fetchSubscription: vi.fn().mockResolvedValue({
      status: null,
      stripePriceId: null,
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
      isActive: false,
    }),
    fetchPrices: vi.fn().mockResolvedValue([]),
  },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));

import { AuthProvider } from '@/contexts/AuthContext';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { Home } from './Home';

function renderHome(state?: unknown) {
  return render(
    <AuthProvider>
      <ThemeProvider>
        <MemoryRouter
          initialEntries={[{ pathname: '/home', state }]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Home />
        </MemoryRouter>
      </ThemeProvider>
    </AuthProvider>,
  );
}

describe('Home', () => {
  it('greets the user by first name and shows their name in the sidebar', async () => {
    renderHome();
    expect(await screen.findByRole('heading', { name: /welcome, ada/i })).toBeInTheDocument();
    expect(screen.getAllByText('Ada Lovelace').length).toBeGreaterThan(0);
  });

  it('opens the billing dialog after a successful checkout', async () => {
    renderHome({ checkoutStatus: 'success' });
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Billing')).toBeInTheDocument();
  });
});
