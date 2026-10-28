import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/userService', () => ({
  userService: {
    fetchProfile: vi.fn(),
    updateProfile: vi.fn(),
  },
}));
vi.mock('@/services/billingService', () => ({
  billingService: {
    fetchBillingMe: vi.fn(),
    fetchPlans: vi.fn(),
    startSubscriptionCheckout: vi.fn(),
    openBillingPortal: vi.fn(),
  },
}));
vi.mock('@/services/inspirationAuthorService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/inspirationAuthorService')>()),
  inspirationAuthorService: { list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/services/xConnectionService', () => ({
  xConnectionService: {
    get: vi.fn(),
    startAuthorization: vi.fn(),
    complete: vi.fn(),
    disconnect: vi.fn(),
  },
}));
vi.mock('@/services/apiKeyService', () => ({
  apiKeyService: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { AuthProvider } from '@/contexts/AuthContext';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { SELLS_PLANS, WITH_OPERATOR } from '@/features/instance/testInstances';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { track } from '@/lib/analytics';
import { fireSuccessConfetti } from '@/lib/confetti';
import type { Instance } from '@/lib/instance';
import { redirectTo } from '@/lib/navigation';
import { apiKeyService } from '@/services/apiKeyService';
import { billingService, type BillingMe, type PlanCatalog } from '@/services/billingService';
import { userService, type UserProfile } from '@/services/userService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import { AppLayout } from './AppLayout';
import { BillingSuccessRedirect } from './BillingRedirect';
import { signedInRoutes } from './signedInRoutes';
import { NOT_SUBSCRIBED, SUBSCRIBED, apiError, renderSignedIn } from './testing/signedInApp';

const ADA: UserProfile = {
  id: 'user_01HZX',
  email: 'ada@example.com',
  firstName: 'Ada',
  lastName: 'Lovelace',
  avatarUrl: null,
};

const CONNECTED: XConnection = {
  handle: 'ada',
  charLimit: 280,
  needsReconnect: false,
  scheduledPostsWaiting: 0,
};

const PERIOD_END = '2030-01-01T00:00:00Z';
const PERIOD_END_LABEL = new Date(PERIOD_END).toLocaleDateString();

const CATALOG: PlanCatalog = {
  plans: [
    {
      key: 'pumpkit_pro_monthly',
      productName: 'Pro',
      amount: 900,
      currency: 'eur',
      interval: 'month',
      intervalCount: 1,
    },
    {
      key: 'pumpkit_pro_yearly',
      productName: 'Pro yearly',
      amount: 9000,
      currency: 'eur',
      interval: 'year',
      intervalCount: 1,
    },
  ],
  termsVersion: '2026-10-11',
};

const WITH_TRIAL: BillingMe = { ...NOT_SUBSCRIBED, trialDays: 14 };

function holding(
  status: NonNullable<BillingMe['subscription']>['status'],
  subscribed: boolean,
  cancelAtPeriodEnd = false,
): BillingMe {
  return {
    subscription: {
      status,
      planKey: 'pumpkit_pro_monthly',
      currentPeriodEnd: PERIOD_END,
      cancelAtPeriodEnd,
    },
    subscribed,
    maySubscribe: false,
    trialDays: null,
  };
}

const ACCEPTANCE_BOXES = [
  /I accept the Terms/,
  /I ask for the service to start immediately/,
  /I specifically approve these clauses/,
];

const NO_PLANS: Instance = { ...SELLS_PLANS, sells_plans: false };

function renderSettings(options: { state?: unknown; instance?: Instance } = {}) {
  return renderSignedIn('/settings', options);
}

async function card(name: string) {
  return within(await screen.findByRole('region', { name }));
}

describe('Settings', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    vi.mocked(userService.fetchProfile).mockReset().mockResolvedValue(ADA);
    vi.mocked(userService.updateProfile).mockReset();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(billingService.fetchPlans).mockReset().mockResolvedValue(CATALOG);
    vi.mocked(billingService.startSubscriptionCheckout)
      .mockReset()
      .mockResolvedValue('https://checkout.stripe.test/s');
    vi.mocked(billingService.openBillingPortal)
      .mockReset()
      .mockResolvedValue('https://portal.stripe.test/x');
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(xConnectionService.startAuthorization).mockReset();
    vi.mocked(xConnectionService.disconnect).mockReset();
    vi.mocked(apiKeyService.list).mockReset().mockResolvedValue([]);
    vi.mocked(redirectTo).mockReset();
    vi.mocked(fireSuccessConfetti).mockReset();
    vi.mocked(track).mockClear();
  });

  it('shows Profile, X account, Plan, API keys and Appearance to a Subscribed User', async () => {
    renderSettings();

    await card('Plan');
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Profile',
      'X account',
      'Plan',
      'API keys',
      'Appearance',
    ]);
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('puts Choose a Plan first for a User who is not Subscribed', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
    renderSettings();

    await card('Choose a Plan');
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Choose a Plan',
      'Profile',
      'X account',
      'Plan',
      'API keys',
      'Appearance',
    ]);
    expect((await card('Plan')).getByText('No Subscription')).toBeInTheDocument();
  });

  describe('Profile', () => {
    it("shows the User's names and their email, read-only, as managed by sign-in", async () => {
      renderSettings();

      const profile = await card('Profile');
      expect(await profile.findByLabelText('First name')).toHaveValue('Ada');
      expect(profile.getByLabelText('Last name')).toHaveValue('Lovelace');
      expect(profile.getByLabelText('Email')).toHaveValue('ada@example.com');
      expect(profile.getByLabelText('Email')).toHaveAttribute('readonly');
      expect(profile.getByText('Managed by sign-in')).toBeInTheDocument();
      expect(profile.getByRole('button', { name: 'Change photo' })).toBeInTheDocument();
      expect(profile.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    });

    it('saves a changed name and shows it in the user card', async () => {
      vi.mocked(userService.updateProfile).mockResolvedValue({ ...ADA, firstName: 'Augusta' });
      renderSettings();

      const profile = await card('Profile');
      fireEvent.change(await profile.findByLabelText('First name'), {
        target: { value: 'Augusta ' },
      });
      fireEvent.click(profile.getByRole('button', { name: 'Save changes' }));

      expect(await profile.findByText('Saved.')).toBeInTheDocument();
      expect(userService.updateProfile).toHaveBeenCalledWith({
        firstName: 'Augusta',
        lastName: 'Lovelace',
        avatarUrl: null,
      });
      expect(
        within(screen.getByRole('link', { name: /your account/i })).getByText('Augusta Lovelace'),
      ).toBeInTheDocument();
      expect(profile.getByRole('button', { name: 'Save changes' })).toBeDisabled();
      expect(track).toHaveBeenCalledWith('account_profile_saved', {
        fields_changed: ['first_name'],
      });
    });

    it('removes the photo', async () => {
      const withPhoto = { ...ADA, avatarUrl: 'data:image/png;base64,AAAA' };
      vi.mocked(userService.fetchProfile).mockResolvedValue(withPhoto);
      vi.mocked(userService.updateProfile).mockResolvedValue(ADA);
      renderSettings();

      const profile = await card('Profile');
      fireEvent.click(await profile.findByRole('button', { name: 'Remove photo' }));
      fireEvent.click(profile.getByRole('button', { name: 'Save changes' }));

      await waitFor(() =>
        expect(userService.updateProfile).toHaveBeenCalledWith({
          firstName: 'Ada',
          lastName: 'Lovelace',
          avatarUrl: null,
        }),
      );
    });

    it('shows why saving failed and keeps the change', async () => {
      vi.mocked(userService.updateProfile).mockRejectedValue(apiError(422, 'Name is too long.'));
      renderSettings();

      const profile = await card('Profile');
      fireEvent.change(await profile.findByLabelText('Last name'), {
        target: { value: 'Byron' },
      });
      fireEvent.click(profile.getByRole('button', { name: 'Save changes' }));

      expect(await profile.findByRole('alert')).toHaveTextContent('Name is too long.');
      expect(profile.getByLabelText('Last name')).toHaveValue('Byron');
      expect(profile.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    });
  });

  describe('X account', () => {
    it('connects X, saying Pumpkit never sees the password', async () => {
      vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
        'https://x.com/i/oauth2/authorize?state=s',
      );
      renderSettings();

      const x = await card('X account');
      expect(x.getByText(/never sees your X password/)).toBeInTheDocument();
      fireEvent.click(await x.findByRole('button', { name: 'Connect X' }));

      await waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
      );
    });

    it('shows the connected handle and disconnects it, warning about waiting Scheduled posts', async () => {
      vi.mocked(xConnectionService.get)
        .mockResolvedValueOnce(CONNECTED)
        .mockResolvedValue({ ...CONNECTED, scheduledPostsWaiting: 3 });
      vi.mocked(xConnectionService.disconnect).mockResolvedValue();
      renderSettings();

      const x = await card('X account');
      expect(await x.findByText('@ada')).toBeInTheDocument();
      fireEvent.click(x.getByRole('button', { name: 'Disconnect' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Disconnect @ada?' }));
      expect(await dialog.findByText(/3 Scheduled posts are waiting/)).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Disconnect' }));

      expect(await x.findByRole('button', { name: 'Connect X' })).toBeInTheDocument();
      expect(x.queryByText('@ada')).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('x_disconnected');
    });

    it('keeps the X connection on screen when disconnecting fails', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(xConnectionService.disconnect).mockRejectedValue(apiError(500, 'Server error'));
      renderSettings();

      const x = await card('X account');
      fireEvent.click(await x.findByRole('button', { name: 'Disconnect' }));
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.click(await dialog.findByRole('button', { name: 'Disconnect' }));

      expect(await x.findByRole('alert')).toHaveTextContent('Server error');
      expect(x.getByText('@ada')).toBeInTheDocument();
    });

    it('shows why connecting failed to start', async () => {
      vi.mocked(xConnectionService.startAuthorization).mockRejectedValue(
        apiError(503, 'X_CLIENT_ID and X_CLIENT_SECRET must be set in .env to connect X accounts.'),
      );
      renderSettings();

      const x = await card('X account');
      fireEvent.click(await x.findByRole('button', { name: 'Connect X' }));

      expect(await x.findByRole('alert')).toHaveTextContent(/X_CLIENT_ID/);
      expect(redirectTo).not.toHaveBeenCalled();
    });

    it('lets a User who is not Subscribed still see and disconnect their X connection', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      renderSettings();

      const x = await card('X account');
      expect(await x.findByText('@ada')).toBeInTheDocument();
      expect(x.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();
    });

    it('shows the message the X callback left behind', async () => {
      renderSettings({ state: { xConnectionNotice: 'Connected @ada.' } });

      expect(await (await card('X account')).findByText('Connected @ada.')).toBeInTheDocument();
    });

    it('says when the X connection could not be loaded', async () => {
      vi.mocked(xConnectionService.get).mockRejectedValue(apiError(500, 'boom'));
      renderSettings();

      expect(await (await card('X account')).findByRole('alert')).toHaveTextContent(
        /couldn't load your x connection/i,
      );
    });

    it('sends a User who is not Subscribed to Choose a Plan instead of connecting', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderSettings();

      const x = await card('X account');
      expect(await x.findByText('Connecting X needs a Subscription.')).toBeInTheDocument();
      expect(x.queryByRole('button', { name: 'Connect X' })).not.toBeInTheDocument();
      expect(x.getByRole('link', { name: 'Subscribe' })).toHaveAttribute(
        'href',
        '/settings#choose-a-plan',
      );
    });
  });

  describe('Plan', () => {
    it.each([
      ['trialing', 'Trial'],
      ['active', 'Active'],
    ] as const)(
      'shows the Plan, a %s status as %s and its renewal date, with Manage subscription',
      async (status, label) => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding(status, true));
        renderSettings();

        const plan = await card('Plan');
        expect(await plan.findByText(label)).toBeInTheDocument();
        expect(plan.getByText('Pro')).toBeInTheDocument();
        expect(plan.getByText(new RegExp(`renews ${PERIOD_END_LABEL}`))).toBeInTheDocument();
        fireEvent.click(plan.getByRole('button', { name: 'Manage subscription' }));

        await waitFor(() =>
          expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'),
        );
        expect(screen.queryByRole('region', { name: 'Choose a Plan' })).not.toBeInTheDocument();
      },
    );

    it('says when a Subscription set to cancel ends', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('active', true, true));
      renderSettings();

      expect(
        await (await card('Plan')).findByText(new RegExp(`ends ${PERIOD_END_LABEL}`)),
      ).toBeInTheDocument();
    });

    it.each([
      ['past_due', true, 'Past due'],
      ['unpaid', false, 'Unpaid'],
    ] as const)(
      'warns that the last payment of a %s Subscription failed and offers Fix payment',
      async (status, subscribed, label) => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding(status, subscribed));
        renderSettings();

        const plan = await card('Plan');
        expect(
          await plan.findByText('Your last payment failed. Update your card to keep access.'),
        ).toBeInTheDocument();
        expect(plan.getByText(label)).toBeInTheDocument();
        fireEvent.click(plan.getByRole('button', { name: 'Fix payment' }));

        await waitFor(() =>
          expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'),
        );
      },
    );

    it('shows why the billing portal could not open', async () => {
      vi.mocked(billingService.openBillingPortal).mockRejectedValue(
        apiError(502, 'Stripe is down.'),
      );
      renderSettings();

      const plan = await card('Plan');
      fireEvent.click(await plan.findByRole('button', { name: 'Manage subscription' }));

      expect(await plan.findByRole('alert')).toHaveTextContent('Stripe is down.');
    });

    it('says when billing could not be loaded', async () => {
      vi.mocked(billingService.fetchBillingMe).mockRejectedValue(apiError(500, 'boom'));
      renderSettings();

      expect(await (await card('Plan')).findByRole('alert')).toHaveTextContent(
        'Could not load billing information.',
      );
    });
  });

  describe('Choose a Plan', () => {
    beforeEach(() => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(WITH_TRIAL);
    });

    it('offers each Plan with its price and the free Trial', async () => {
      renderSettings();

      const choose = await card('Choose a Plan');
      expect(await choose.findByText('Pro')).toBeInTheDocument();
      expect(choose.getByText('Pro yearly')).toBeInTheDocument();
      expect(choose.getByText(/€9\.00 \/ month/)).toBeInTheDocument();
      expect(choose.getAllByText('14-day free Trial')).toHaveLength(2);
    });

    it('offers the Plans to a User whose Subscription is still incomplete', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
        ...holding('incomplete', false),
        maySubscribe: true,
      });
      renderSettings();

      const choose = await card('Choose a Plan');
      expect(await choose.findByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
      expect(
        (await card('Plan')).queryByRole('button', { name: /manage/i }),
      ).not.toBeInTheDocument();
    });

    it('keeps "Start free Trial" disabled until the three boxes are ticked, then starts checkout', async () => {
      renderSettings();

      const choose = await card('Choose a Plan');
      const start = await choose.findByRole('button', { name: 'Start free Trial of Pro yearly' });
      for (const box of ACCEPTANCE_BOXES) {
        expect(start).toBeDisabled();
        fireEvent.click(choose.getByRole('checkbox', { name: box }));
      }
      fireEvent.click(start);

      await waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://checkout.stripe.test/s'),
      );
      expect(billingService.startSubscriptionCheckout).toHaveBeenCalledWith(
        'pumpkit_pro_yearly',
        '2026-10-11',
        { acceptedTerms: true, requestedImmediateStart: true, approvedSpecificClauses: true },
      );
      expect(track).toHaveBeenCalledWith('billing_subscription_checkout_started', {
        plan_key: 'pumpkit_pro_yearly',
      });
    });

    it('links each acceptance box to what it refers to in the Terms', async () => {
      renderSettings();

      const choose = await card('Choose a Plan');
      await choose.findByRole('button', { name: 'Start free Trial of Pro' });
      const href = (name: RegExp) => choose.getByRole('link', { name }).getAttribute('href');
      expect(href(/^Terms$/)).toBe('/terms');
      expect(href(/^Privacy Policy$/)).toBe('/privacy');
      expect(href(/withdrawal/i)).toBe('/terms#withdrawal');
      expect(href(/13\. No refunds/)).toBe('/terms#refunds');
      expect(href(/20\. Competent court/)).toBe('/terms#courts');
    });

    it('says Subscribe for a User who gets no Trial', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderSettings();

      const choose = await card('Choose a Plan');
      expect(await choose.findByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
      expect(choose.queryByText(/free Trial/)).not.toBeInTheDocument();
    });

    it('starts checkout with only the Plan key where the Instance has no Terms', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, termsVersion: null });
      renderSettings();

      const choose = await card('Choose a Plan');
      const start = await choose.findByRole('button', { name: 'Start free Trial of Pro' });
      expect(choose.queryByRole('checkbox')).not.toBeInTheDocument();
      fireEvent.click(start);

      await waitFor(() =>
        expect(billingService.startSubscriptionCheckout).toHaveBeenCalledWith(
          'pumpkit_pro_monthly',
          null,
          expect.anything(),
        ),
      );
    });

    it('asks the User to review the Terms when checkout says they have changed', async () => {
      const changed =
        'The Terms have changed. Please review the current Terms and accept them again.';
      vi.mocked(billingService.startSubscriptionCheckout).mockRejectedValue(apiError(409, changed));
      renderSettings();

      const choose = await card('Choose a Plan');
      const start = await choose.findByRole('button', { name: 'Start free Trial of Pro' });
      for (const box of ACCEPTANCE_BOXES)
        fireEvent.click(choose.getByRole('checkbox', { name: box }));
      fireEvent.click(start);

      expect(await choose.findByRole('alert')).toHaveTextContent(changed);
      expect(redirectTo).not.toHaveBeenCalled();
    });
  });

  describe('Return from checkout', () => {
    it('plays the celebration and shows the new Subscription', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('trialing', true));
      renderSettings({ state: { checkoutStatus: 'success' } });

      expect(await (await card('Plan')).findByText('Trial')).toBeInTheDocument();
      expect(fireSuccessConfetti).toHaveBeenCalledTimes(1);
      expect(track).toHaveBeenCalledWith('billing_checkout_succeeded');
    });

    it('says a cancelled checkout charged nothing, beside the Plans', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderSettings({ state: { checkoutStatus: 'cancelled' } });

      const choose = await card('Choose a Plan');
      expect(
        await choose.findByText('Checkout was cancelled. You have not been charged.'),
      ).toBeInTheDocument();
      expect(fireSuccessConfetti).not.toHaveBeenCalled();
      expect(track).toHaveBeenCalledWith('billing_checkout_cancelled');
    });

    it('lands on Settings from the success URL', async () => {
      render(
        <InstanceProvider instance={SELLS_PLANS}>
          <AuthProvider>
            <ThemeProvider>
              <MemoryRouter
                initialEntries={['/billing/success']}
                future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
              >
                <Routes>
                  <Route path="/billing/success" element={<BillingSuccessRedirect />} />
                  <Route element={<AppLayout />}>{signedInRoutes()}</Route>
                </Routes>
              </MemoryRouter>
            </ThemeProvider>
          </AuthProvider>
        </InstanceProvider>,
      );

      expect(
        await screen.findByRole('heading', { level: 1, name: 'Settings' }),
      ).toBeInTheDocument();
      await waitFor(() => expect(fireSuccessConfetti).toHaveBeenCalledTimes(1));
    });
  });

  describe('On an Instance that sells no Plans', () => {
    it('shows neither Choose a Plan nor Plan, and asks nothing about billing', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderSettings({ instance: NO_PLANS });

      await card('Profile');
      expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
        'Profile',
        'X account',
        'API keys',
        'Appearance',
      ]);
      expect(
        await (await card('X account')).findByRole('button', { name: 'Connect X' }),
      ).toBeInTheDocument();
      expect(billingService.fetchBillingMe).not.toHaveBeenCalled();
    });

    it('ignores a return from checkout', async () => {
      renderSettings({ instance: NO_PLANS, state: { checkoutStatus: 'success' } });

      await card('Profile');
      expect(fireSuccessConfetti).not.toHaveBeenCalled();
    });
  });

  describe('API keys', () => {
    it('creates a key, shows its secret once, and revokes it', async () => {
      vi.mocked(apiKeyService.create).mockResolvedValue({
        apiKey: {
          id: 'api_key_1',
          name: 'Work laptop',
          prefix: 'pumpkit_AbCd1234',
          createdAt: '2026-10-01T09:00:00Z',
          lastUsedAt: null,
        },
        secret: 'pumpkit_AbCd1234-secret',
        claudeCommand: 'claude mcp add pumpkit',
      });
      vi.mocked(apiKeyService.revoke).mockResolvedValue();
      renderSettings();

      const keys = await card('API keys');
      await keys.findByText(/No API keys yet/);
      fireEvent.change(keys.getByLabelText('Key name'), { target: { value: 'Work laptop' } });
      fireEvent.click(keys.getByRole('button', { name: 'Create key' }));
      expect(await keys.findByText('pumpkit_AbCd1234-secret')).toBeInTheDocument();

      fireEvent.click(keys.getByRole('button', { name: 'Revoke Work laptop' }));
      fireEvent.click(await keys.findByRole('button', { name: 'Revoke key' }));

      await waitFor(() => expect(apiKeyService.revoke).toHaveBeenCalledWith('api_key_1'));
    });
  });

  describe('Appearance', () => {
    it('starts on System and switches to Dark, which a reload keeps', async () => {
      const { unmount } = renderSettings();

      const appearance = await card('Appearance');
      expect(appearance.getByRole('radio', { name: 'System' })).toBeChecked();
      fireEvent.click(appearance.getByRole('radio', { name: 'Dark' }));

      expect(document.documentElement).toHaveClass('dark');
      expect(track).toHaveBeenCalledWith('settings_theme_changed', { theme: 'dark' });
      unmount();
      renderSettings();
      expect((await card('Appearance')).getByRole('radio', { name: 'Dark' })).toBeChecked();
    });

    it('switches to Light', async () => {
      renderSettings();

      const appearance = await card('Appearance');
      fireEvent.click(appearance.getByRole('radio', { name: 'Light' }));

      expect(appearance.getByRole('radio', { name: 'Light' })).toBeChecked();
      expect(document.documentElement).not.toHaveClass('dark');
    });
  });

  describe('Footer', () => {
    const ANALYTICS = {
      key: 'phc_test',
      host: 'https://eu.i.posthog.com',
      ui_host: 'https://eu.posthog.com',
    };

    it('links to the Privacy Policy and the Terms in a new tab', async () => {
      renderSettings({ instance: WITH_OPERATOR });

      const legal = within(await screen.findByRole('navigation', { name: 'Legal' }));
      const privacy = legal.getByRole('link', { name: 'Privacy Policy' });
      const terms = legal.getByRole('link', { name: 'Terms' });
      expect(privacy).toHaveAttribute('href', '/privacy');
      expect(terms).toHaveAttribute('href', '/terms');
      for (const link of [privacy, terms]) expect(link).toHaveAttribute('target', '_blank');
    });

    it('offers Cookie settings next to the legal links', async () => {
      renderSettings({ instance: { ...WITH_OPERATOR, analytics: ANALYTICS } });

      const legal = within(await screen.findByRole('navigation', { name: 'Legal' }));
      expect(legal.getByRole('button', { name: 'Cookie settings' })).toBeInTheDocument();
    });

    it('offers only Cookie settings on an Instance with analytics but no Operator details', async () => {
      renderSettings({ instance: { ...SELLS_PLANS, analytics: ANALYTICS } });

      expect(await screen.findByRole('button', { name: 'Cookie settings' })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Privacy Policy' })).not.toBeInTheDocument();
    });

    it('has no legal links or Cookie settings on an Instance with neither', async () => {
      renderSettings();

      await card('Profile');
      expect(screen.queryByRole('link', { name: 'Privacy Policy' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Cookie settings' })).not.toBeInTheDocument();
    });
  });
});
