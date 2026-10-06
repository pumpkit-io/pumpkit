import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
    fetchBillingMe: vi.fn(),
    fetchPlans: vi.fn().mockResolvedValue([]),
  },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));
vi.mock('@/services/inspirationAuthorService', () => ({
  inspirationAuthorService: {
    list: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
  },
}));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { AuthProvider } from '@/contexts/AuthContext';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { track } from '@/lib/analytics';
import { billingService } from '@/services/billingService';
import {
  inspirationAuthorService,
  type InspirationAuthor,
} from '@/services/inspirationAuthorService';
import { Home } from './Home';

const NOT_SUBSCRIBED = {
  subscription: null,
  subscribed: false,
  maySubscribe: true,
  trialDays: null,
};
const SUBSCRIBED = {
  subscription: {
    status: 'active' as const,
    planKey: 'pumpkit_pro_monthly',
    currentPeriodEnd: null,
    cancelAtPeriodEnd: false,
  },
  subscribed: true,
  maySubscribe: false,
  trialDays: null,
};

const LEVELSIO: InspirationAuthor = {
  handle: 'levelsio',
  lastFetchedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
  postCount: 18,
};
const PAULG: InspirationAuthor = {
  handle: 'paulg',
  lastFetchedAt: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  postCount: 20,
};

/** An axios-shaped rejection carrying the backend's status and `detail`. */
function apiError(status: number, detail: string) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

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

async function authorsPanel() {
  return within(await screen.findByRole('region', { name: 'Inspiration authors' }));
}

describe('Home', () => {
  beforeEach(() => {
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([]);
    vi.mocked(inspirationAuthorService.add).mockReset();
    vi.mocked(inspirationAuthorService.remove).mockReset();
    vi.mocked(track).mockClear();
  });

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

  describe('Inspiration authors', () => {
    it('lists the authors in order with when their posts were last fetched and how many are stored', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderHome();

      const panel = await authorsPanel();
      const items = await panel.findAllByRole('listitem');
      expect(items.map((item) => within(item).getByText(/^@/).textContent)).toEqual([
        '@levelsio',
        '@paulg',
      ]);
      expect(within(items[0]).getByText('Fetched 2 hours ago · 18 posts')).toBeInTheDocument();
      expect(within(items[1]).getByText('Fetched 5 minutes ago · 20 posts')).toBeInTheDocument();
    });

    it('says how to start when the User has no authors', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderHome();

      const panel = await authorsPanel();
      expect(await panel.findByText(/no inspiration authors yet/i)).toBeInTheDocument();
    });

    it('adds a handle, shows it in the list and clears the field', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.add).mockResolvedValue(LEVELSIO);
      renderHome();

      const panel = await authorsPanel();
      const field = await panel.findByLabelText('X handle');
      fireEvent.change(field, { target: { value: '@LevelsIO' } });
      fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

      expect(await panel.findByText('@levelsio')).toBeInTheDocument();
      expect(inspirationAuthorService.add).toHaveBeenCalledWith('@LevelsIO');
      expect(field).toHaveValue('');
      expect(track).toHaveBeenCalledWith('inspiration_author_added');
    });

    it.each([
      [404, "@nobody doesn't exist on X."],
      [422, '@nobody has no original posts to learn from.'],
      [409, 'You can have up to 3 Inspiration authors. Remove one to add another.'],
    ])(
      'says why a handle was refused with a %i and keeps it in the field',
      async (status, detail) => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
        vi.mocked(inspirationAuthorService.add).mockRejectedValue(apiError(status, detail));
        renderHome();

        const panel = await authorsPanel();
        const field = await panel.findByLabelText('X handle');
        fireEvent.change(field, { target: { value: 'nobody' } });
        fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

        expect(await panel.findByRole('alert')).toHaveTextContent(detail);
        expect(field).toHaveValue('nobody');
        expect(track).not.toHaveBeenCalledWith('inspiration_author_added');
      },
    );

    it('removes an author from the list', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      vi.mocked(inspirationAuthorService.remove).mockResolvedValue(undefined);
      renderHome();

      const panel = await authorsPanel();
      fireEvent.click(await panel.findByRole('button', { name: 'Remove @levelsio' }));

      await waitFor(() => expect(panel.queryByText('@levelsio')).not.toBeInTheDocument());
      expect(panel.getByText('@paulg')).toBeInTheDocument();
      expect(inspirationAuthorService.remove).toHaveBeenCalledWith('levelsio');
      expect(track).toHaveBeenCalledWith('inspiration_author_removed');
    });

    it('shows a User who is not Subscribed their authors and a prompt to subscribe that opens Billing', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderHome();

      const panel = await authorsPanel();
      expect(await panel.findByText('@levelsio')).toBeInTheDocument();
      expect(await panel.findByText(/needs a subscription/i)).toBeInTheDocument();
      expect(panel.queryByLabelText('X handle')).not.toBeInTheDocument();
      expect(panel.queryByRole('button', { name: 'Remove @levelsio' })).not.toBeInTheDocument();

      fireEvent.click(panel.getByRole('button', { name: 'Subscribe' }));
      expect(await screen.findByRole('dialog')).toBeInTheDocument();
    });

    it('shows the prompt to subscribe when adding is refused with a 403', async () => {
      vi.mocked(billingService.fetchBillingMe)
        .mockResolvedValueOnce(SUBSCRIBED)
        .mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(inspirationAuthorService.add).mockRejectedValue(
        apiError(403, 'This needs a Subscription. Subscribe to continue.'),
      );
      renderHome();

      const panel = await authorsPanel();
      fireEvent.change(await panel.findByLabelText('X handle'), { target: { value: 'levelsio' } });
      fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

      expect(await panel.findByRole('button', { name: 'Subscribe' })).toBeInTheDocument();
    });
  });
});
