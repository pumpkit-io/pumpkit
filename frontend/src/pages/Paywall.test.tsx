import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
    fetchPlans: vi.fn(),
    startSubscriptionCheckout: vi.fn(),
    openBillingPortal: vi.fn(),
  },
}));
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn() },
}));
vi.mock('@/services/inspirationAuthorService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/inspirationAuthorService')>()),
  inspirationAuthorService: { list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/services/xConnectionService', () => ({
  xConnectionService: { get: vi.fn().mockResolvedValue(null) },
}));
vi.mock('@/services/apiKeyService', () => ({
  apiKeyService: { list: vi.fn().mockResolvedValue([]), create: vi.fn() },
}));
vi.mock('@/services/postService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/postService')>()),
  postService: {
    list: vi.fn().mockResolvedValue({
      posts: [],
      counts: { draft: 0, scheduled: 0, published: 0, failed: 0 },
      nextOffset: null,
    }),
    get: vi.fn().mockReturnValue(new Promise(() => {})),
  },
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
import { OnboardingProvider } from '@/features/onboarding/OnboardingProvider';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { track } from '@/lib/analytics';
import { fireSuccessConfetti } from '@/lib/confetti';
import { redirectTo } from '@/lib/navigation';
import { apiKeyService } from '@/services/apiKeyService';
import { session } from '@/lib/session';
import { billingService, type BillingMe, type PlanCatalog } from '@/services/billingService';
import { onboardingService } from '@/services/onboardingService';
import { BillingSuccessRedirect } from './BillingRedirect';
import { SignedInHome } from './SignedInHome';
import { signedInRoutes } from './signedInRoutes';
import {
  NOT_SUBSCRIBED,
  SUBSCRIBED,
  apiError,
  currentPath,
  renderSignedIn,
} from './testing/signedInApp';

const CATALOG: PlanCatalog = {
  plans: [
    {
      key: 'pumpkit_pro_monthly',
      productName: 'Pumpkit Pro',
      amount: 900,
      currency: 'eur',
      interval: 'month',
      intervalCount: 1,
    },
    {
      key: 'pumpkit_pro_yearly',
      productName: 'Pumpkit Pro',
      amount: 9000,
      currency: 'eur',
      interval: 'year',
      intervalCount: 1,
    },
  ],
  termsVersion: '2026-10-11',
  allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
  trial: { days: 7, generations: 125, xPosts: 25, linkXPosts: 2 },
  topUp: null,
};

const WITH_TRIAL: BillingMe = { ...NOT_SUBSCRIBED, trialDays: 7 };

const ACCEPTANCE_BOXES = [
  /I accept the Terms/,
  /I ask for the service to start immediately/,
  /I specifically approve these clauses/,
];

function holding(status: NonNullable<BillingMe['subscription']>['status']): BillingMe {
  return {
    subscription: {
      status,
      planKey: 'pumpkit_pro_monthly',
      currentPeriodEnd: null,
      cancelAtPeriodEnd: false,
    },
    subscribed: false,
    maySubscribe: status === 'incomplete',
    trialDays: null,
  };
}

function renderPaywall(options: Parameters<typeof renderSignedIn>[1] = {}) {
  return renderSignedIn('/subscribe', { nextStep: 'paywall', ...options });
}

async function paywall() {
  return within(await screen.findByRole('main'));
}

function tickEveryBox(area: ReturnType<typeof within>) {
  for (const box of ACCEPTANCE_BOXES) fireEvent.click(area.getByRole('checkbox', { name: box }));
}

describe('Paywall', () => {
  beforeEach(() => {
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(WITH_TRIAL);
    vi.mocked(billingService.fetchPlans).mockReset().mockResolvedValue(CATALOG);
    vi.mocked(billingService.startSubscriptionCheckout)
      .mockReset()
      .mockResolvedValue('https://checkout.stripe.test/s');
    vi.mocked(billingService.openBillingPortal)
      .mockReset()
      .mockResolvedValue('https://portal.stripe.test/x');
    vi.mocked(onboardingService.fetchNextStep).mockReset().mockResolvedValue('paywall');
    vi.mocked(redirectTo).mockReset();
    vi.mocked(fireSuccessConfetti).mockReset();
    vi.mocked(track).mockClear();
  });

  afterEach(() => vi.useRealTimers());

  describe('Routing', () => {
    it.each(['/new', '/posts/post_1', '/settings', '/persona'])(
      'sends %s to the Paywall while the User is not Subscribed',
      async (path) => {
        renderSignedIn(path, { nextStep: 'paywall' });

        expect(
          await screen.findByRole('heading', { level: 1, name: 'Start your free trial' }),
        ).toBeInTheDocument();
        expect(currentPath()).toBe('/subscribe');
        expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
      },
    );

    it('sends a Subscribed User on from the Paywall to New post', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderSignedIn('/subscribe', { nextStep: null });

      await waitFor(() => expect(currentPath()).toBe('/new'));
    });

    it('routes / by the next step', async () => {
      renderSignedIn('/', { nextStep: 'paywall' });

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });

    it('sends a User whose Subscription ended to the Paywall from a refused write', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('paywall');
      vi.mocked(apiKeyService.create).mockRejectedValue(
        apiError(403, 'This needs a subscription. Subscribe to continue.'),
      );
      renderSignedIn('/settings', { nextStep: null });

      fireEvent.change(await screen.findByLabelText('Key name'), {
        target: { value: 'Work laptop' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Create key' }));

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });
  });

  describe('Back from checkout', () => {
    it('celebrates a successful checkout and lands on New post', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderSignedIn('/', { nextStep: null, state: { checkoutStatus: 'success' } });

      await waitFor(() => expect(currentPath()).toBe('/new'));
      expect(fireSuccessConfetti).toHaveBeenCalledTimes(1);
      expect(track).toHaveBeenCalledWith('billing_checkout_succeeded');
    });

    it('waits for the Subscription to reach Pumpkit before leaving the Paywall', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
      renderSignedIn('/', { nextStep: 'paywall', state: { checkoutStatus: 'success' } });

      expect(await screen.findByText('Confirming your subscription…')).toBeInTheDocument();
      await waitFor(() => expect(currentPath()).toBe('/new'), { timeout: 3000 });
    });

    it('lands on / from the success URL, then on New post', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      render(
        <InstanceProvider instance={SELLS_PLANS}>
          <AuthProvider>
            <OnboardingProvider initialNextStep={null}>
              <ThemeProvider>
                <MemoryRouter
                  initialEntries={['/billing/success']}
                  future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
                >
                  <Routes>
                    <Route path="/billing/success" element={<BillingSuccessRedirect />} />
                    <Route path="/" element={<SignedInHome />} />
                    {signedInRoutes()}
                  </Routes>
                </MemoryRouter>
              </ThemeProvider>
            </OnboardingProvider>
          </AuthProvider>
        </InstanceProvider>,
      );

      expect(
        await screen.findByRole('heading', { name: "What's the post about?" }),
      ).toBeInTheDocument();
      expect(fireSuccessConfetti).toHaveBeenCalledTimes(1);
    });

    it('says a cancelled checkout charged nothing, above the Plans', async () => {
      renderSignedIn('/', { nextStep: 'paywall', state: { checkoutStatus: 'cancelled' } });

      const area = await paywall();
      expect(
        await area.findByText("Checkout cancelled. Pick a plan when you're ready."),
      ).toBeInTheDocument();
      expect(currentPath()).toBe('/subscribe');
      expect(fireSuccessConfetti).not.toHaveBeenCalled();
      expect(track).toHaveBeenCalledWith('billing_checkout_cancelled');
    });
  });

  describe('Trial', () => {
    it('offers each Plan with its real price, the yearly saving and the first charge date', async () => {
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(new Date('2026-10-31T12:00:00'));
      renderPaywall();

      const area = await paywall();
      expect(await area.findByText('7 days free, then billed by the plan you pick.')).toBeVisible();
      expect(area.getByText('€9.00 / month')).toBeInTheDocument();
      expect(area.getByText('€90.00 / year')).toBeInTheDocument();
      expect(area.getByText('Saves 17% vs monthly')).toBeInTheDocument();
      expect(area.getByText(/You won.t be charged until Nov 7, 2026\./)).toBeInTheDocument();
      expect(area.getAllByRole('button', { name: /^Start trial: / })).toHaveLength(2);
      expect(track).toHaveBeenCalledWith('paywall_viewed');
    });

    it("lists what the Plan allows and the Trial's limits, with the Instance's caps", async () => {
      renderPaywall();

      const offer = within(await (await paywall()).findByRole('list', { name: 'Included' }));
      expect(offer.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        '500 post generations a month.',
        'Publish 100 X posts a month, up to 10 of them with a link.',
        'Write in the voice of your favorite X creators.',
        '7-day free trial: 125 generations and 25 X posts, up to 2 with a link.',
      ]);
    });

    it('explains what counts as a generation', async () => {
      renderPaywall();

      fireEvent.click(await (await paywall()).findByRole('button', { name: 'About generations' }));

      expect(await screen.findByRole('dialog', { name: 'About generations' })).toHaveTextContent(
        'Every prompt to generate or refine a post counts as one generation.',
      );
    });

    it('drops the line of a cap the Instance leaves empty', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({
        ...CATALOG,
        allowance: { generations: null, xPosts: 100, linkXPosts: null },
        trial: { days: 7, generations: null, xPosts: 25, linkXPosts: null },
      });
      renderPaywall();

      const area = await paywall();
      const offer = within(await area.findByRole('list', { name: 'Included' }));
      expect(offer.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        'Publish 100 X posts a month.',
        'Write in the voice of your favorite X creators.',
        '7-day free trial: 25 X posts.',
      ]);
      expect(area.queryByRole('button', { name: 'About generations' })).not.toBeInTheDocument();
    });

    it('keeps "Start trial" disabled until the three boxes are ticked, then starts checkout', async () => {
      renderPaywall();

      const area = await paywall();
      const start = await area.findByRole('button', { name: 'Start trial: Yearly' });
      for (const box of ACCEPTANCE_BOXES) {
        expect(start).toBeDisabled();
        fireEvent.click(area.getByRole('checkbox', { name: box }));
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
      renderPaywall();

      const area = await paywall();
      await area.findByRole('button', { name: 'Start trial: Monthly' });
      const box = within(area.getByRole('group', { name: 'Accept the Terms' }));
      const href = (name: RegExp) => box.getByRole('link', { name }).getAttribute('href');
      expect(href(/^Terms$/)).toBe('/terms');
      expect(href(/^Privacy Policy$/)).toBe('/privacy');
      expect(href(/withdrawal/i)).toBe('/terms#withdrawal');
      expect(href(/14\. No refunds/)).toBe('/terms#refunds');
    });

    it('starts checkout with only the Plan key where the Instance has no Terms', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, termsVersion: null });
      renderPaywall();

      const area = await paywall();
      const start = await area.findByRole('button', { name: 'Start trial: Monthly' });
      expect(area.queryByRole('checkbox')).not.toBeInTheDocument();
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
      renderPaywall();

      const area = await paywall();
      const start = await area.findByRole('button', { name: 'Start trial: Monthly' });
      tickEveryBox(area);
      fireEvent.click(start);

      expect(await area.findByRole('alert')).toHaveTextContent(changed);
      expect(redirectTo).not.toHaveBeenCalled();
    });
  });

  describe('Subscribe', () => {
    it('offers Subscribe and no charge date to a User whose Trial is used up', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderPaywall();

      const area = await paywall();
      expect(
        await area.findByRole('heading', { level: 1, name: 'Subscribe to keep writing' }),
      ).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Subscribe: Monthly' })).toBeInTheDocument();
      expect(area.queryByText(/free/)).not.toBeInTheDocument();
      expect(area.queryByText(/won.t be charged/)).not.toBeInTheDocument();
      expect(area.getByRole('list', { name: 'Included' })).not.toHaveTextContent(/trial/);
    });
  });

  describe('States', () => {
    it('shows two card skeletons while the plans load', async () => {
      vi.mocked(billingService.fetchPlans).mockReturnValue(new Promise(() => {}));
      renderPaywall();

      expect(await screen.findByRole('status', { name: 'Loading plans' })).toBeInTheDocument();
    });

    it('says when the plans could not load, and tries again', async () => {
      vi.mocked(billingService.fetchPlans).mockRejectedValueOnce(new Error('Network Error'));
      renderPaywall();

      const area = await paywall();
      expect(await area.findByRole('alert')).toHaveTextContent("Couldn't load plans.");
      fireEvent.click(area.getByRole('button', { name: 'Try again' }));

      expect(await area.findByRole('button', { name: 'Start trial: Monthly' })).toBeVisible();
    });

    it('offers the billing portal in place of the Plans while the first payment processes', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('incomplete'));
      renderPaywall();

      const area = await paywall();
      expect(
        await area.findByRole('heading', { name: 'Your payment is still processing' }),
      ).toBeInTheDocument();
      expect(area.queryByRole('button', { name: /^Subscribe: / })).not.toBeInTheDocument();
      fireEvent.click(area.getByRole('button', { name: 'Open billing portal' }));

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'));
    });

    it('offers the billing portal to a User whose Subscription is on hold over a payment', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('unpaid'));
      renderPaywall();

      const area = await paywall();
      expect(
        await area.findByRole('heading', { name: 'Your subscription is on hold' }),
      ).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Open billing portal' })).toBeInTheDocument();
    });
  });

  describe('Shell', () => {
    it('shows the steps with the Plan current, and no sidebar', async () => {
      renderPaywall();

      const steps = within(await screen.findByRole('navigation', { name: 'Steps' }));
      const listed = within(steps.getByRole('list'));
      expect(listed.getAllByRole('listitem').map((step) => step.textContent)).toEqual([
        '1Plan',
        '2Connect X',
        '3Persona',
      ]);
      expect(listed.getByText('Plan').closest('[aria-current="step"]')).not.toBeNull();
      expect(steps.getByText(/Step 1 of 3/)).toBeInTheDocument();
      expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
    });

    it('links the Terms, the Privacy Policy and the company details', async () => {
      renderPaywall({ instance: WITH_OPERATOR });

      const legal = within(await screen.findByRole('navigation', { name: 'Legal' }));
      expect(legal.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
      expect(legal.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute(
        'href',
        '/privacy',
      );
      expect(legal.getByRole('link', { name: 'Company details' })).toHaveAttribute(
        'href',
        '/terms#operator',
      );
    });

    it('signs out from the account menu, which names the User', async () => {
      const end = vi.spyOn(session, 'end').mockResolvedValue();
      renderPaywall();

      const trigger = await screen.findByRole('button', { name: 'Your account' });
      fireEvent.keyDown(trigger, { key: 'Enter' });
      expect(await screen.findByText('ada@example.com')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));

      expect(end).toHaveBeenCalledWith('user');
      end.mockRestore();
    });
  });
});
