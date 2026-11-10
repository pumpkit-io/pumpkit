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
    previewCoupon: vi.fn(),
    redeemCoupon: vi.fn(),
    fetchCouponRedemption: vi.fn(),
    fetchPaidSignup: vi.fn(),
    fetchPlanChange: vi.fn(),
    cancelPaidSignup: vi.fn(),
    createPaidSignup: vi.fn(),
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
  xConnectionService: { get: vi.fn().mockResolvedValue(null), startAuthorization: vi.fn() },
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
import { xConnectionService } from '@/services/xConnectionService';
import { fireSuccessConfetti } from '@/lib/confetti';
import { redirectTo } from '@/lib/navigation';
import { session } from '@/lib/session';
import { storageKey } from '@/lib/storage';
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
  couponsEnabled: false,
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
      cancelAt: null,
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
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(xConnectionService.startAuthorization).mockReset();
  });

  afterEach(() => vi.useRealTimers());

  it('offers publishing recovery without requiring the User to buy access', async () => {
    vi.mocked(xConnectionService.get).mockResolvedValue({
      handle: 'ada',
      charLimit: 280,
      premium: false,
      needsReconnect: true,
      needsReconnectForMedia: false,
      scheduledPostsWaiting: 1,
      photoUrl: null,
      offerPhoto: false,
    });
    vi.mocked(xConnectionService.startAuthorization).mockResolvedValue('https://x.com/i/oauth2');
    renderPaywall();

    const banner = within(await screen.findByRole('region', { name: 'Reconnect X' }));
    fireEvent.click(banner.getByRole('button', { name: 'Reconnect X' }));

    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2'));
    expect(currentPath()).toBe('/subscribe');
  });

  it('announces the expected-account recovery error on the paywall', async () => {
    vi.mocked(xConnectionService.get).mockResolvedValue({
      handle: 'ada',
      charLimit: 280,
      premium: false,
      needsReconnect: true,
      needsReconnectForMedia: false,
      scheduledPostsWaiting: 1,
      photoUrl: null,
      offerPhoto: false,
    });
    const detail = 'Reconnect the same X account, @ada. Sign out of X and retry with that account.';
    renderPaywall({ state: { xConnectionNotice: detail } });

    const banner = within(await screen.findByRole('region', { name: 'Reconnect X' }));

    expect(banner.getByRole('alert')).toHaveTextContent(detail);
  });

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
        'Schedule posts and threads to X.',
        'Use it from Claude Code, Codex, Cursor or Gemini CLI.',
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

    it('explains which AI tools can use Pumpkit', async () => {
      renderPaywall();

      fireEvent.click(await (await paywall()).findByRole('button', { name: 'About AI tools' }));

      expect(await screen.findByRole('dialog', { name: 'About AI tools' })).toHaveTextContent(
        'Pumpkit is an MCP server: any AI tool that supports MCP can use it to write, revise and schedule posts.',
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
        'Schedule posts and threads to X.',
        'Use it from Claude Code, Codex, Cursor or Gemini CLI.',
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
        '2Persona',
      ]);
      expect(listed.getByText('Plan').closest('[aria-current="step"]')).not.toBeNull();
      expect(steps.getByText(/Step 1 of 2/)).toBeInTheDocument();
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

const COUPON_OFFER = {
  months: 3,
  startsAt: '2028-01-31T12:00:00Z',
  endsAt: '2028-04-30T12:00:00Z',
  allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
  nextPaymentAt: null,
  termsVersion: '2026-11-08',
  revision: 'signed-preview',
};
const COUPON_RESULT = {
  operationId: 'result',
  months: 3,
  startsAt: '2028-01-31T12:01:00Z',
  endsAt: '2028-04-30T12:01:00Z',
};
async function reviewCoupon() {
  fireEvent.click(await screen.findByRole('button', { name: 'Have a coupon?' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Coupon code' }), {
    target: { value: 'private-code' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Check code' }));
  const fields = within(
    await screen.findByRole('group', { name: 'Accept the Terms for free access' }),
  );
  for (const box of fields.getAllByRole('checkbox')) fireEvent.click(box);
}

describe('Coupon preview on the Paywall', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(billingService.redeemCoupon).mockReset().mockResolvedValue(COUPON_RESULT);
    vi.mocked(billingService.fetchCouponRedemption).mockReset();
    vi.mocked(billingService.previewCoupon).mockReset().mockResolvedValue(COUPON_OFFER);
    vi.mocked(billingService.startSubscriptionCheckout).mockClear();
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(WITH_TRIAL);
    vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, couponsEnabled: true });
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('paywall');
  });

  it('requires two cardless acceptance boxes before redeeming without paid checkout', async () => {
    vi.mocked(billingService.previewCoupon).mockResolvedValue({
      months: 3,
      startsAt: '2028-01-31T12:00:00Z',
      endsAt: '2028-04-30T12:00:00Z',
      allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
      nextPaymentAt: null,
      termsVersion: '2026-11-08',
      revision: 'signed-preview',
    });
    renderPaywall();
    fireEvent.click(await screen.findByRole('button', { name: 'Have a coupon?' }));
    const input = screen.getByRole('textbox', { name: 'Coupon code' });
    expect(input).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Check code' })).toBeDisabled();
    fireEvent.change(input, { target: { value: 'private-code' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByText('3 free months')).toBeInTheDocument();
    expect(screen.getByText('No automatic payment')).toBeInTheDocument();
    expect(screen.getByText(/500 generations/)).toBeInTheDocument();
    expect(
      screen.getByText(/This creates no subscription or obligation to pay/),
    ).toBeInTheDocument();
    expect(billingService.previewCoupon).toHaveBeenCalledWith('private-code');
    const confirmation = within(
      screen.getByRole('group', { name: 'Accept the Terms for free access' }),
    );
    expect(confirmation.getAllByRole('checkbox')).toHaveLength(2);
    const redeem = screen.getByRole('button', { name: 'Redeem coupon' });
    expect(redeem).toBeDisabled();
    for (const box of confirmation.getAllByRole('checkbox')) fireEvent.click(box);
    vi.mocked(billingService.redeemCoupon).mockResolvedValue({
      operationId: 'result',
      months: 3,
      startsAt: '2028-01-31T12:01:00Z',
      endsAt: '2028-04-30T12:01:00Z',
    });
    fireEvent.click(redeem);
    expect(await screen.findByText('Coupon redeemed')).toHaveFocus();
    expect(billingService.redeemCoupon).toHaveBeenCalledWith(
      expect.objectContaining({
        revision: 'signed-preview',
        termsVersion: '2026-11-08',
        acceptedTerms: true,
        approvedSpecificClauses: true,
        language: 'en',
      }),
    );
    expect(billingService.startSubscriptionCheckout).not.toHaveBeenCalled();
  });

  it('redeems without acceptance boxes on an Instance with no Terms', async () => {
    vi.mocked(billingService.previewCoupon).mockResolvedValue({
      ...COUPON_OFFER,
      termsVersion: null,
    });
    renderPaywall();
    fireEvent.click(await screen.findByRole('button', { name: 'Have a coupon?' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Coupon code' }), {
      target: { value: 'private-code' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Check code' }));
    const redeem = await screen.findByRole('button', { name: 'Redeem coupon' });
    expect(
      screen.queryByRole('group', { name: 'Accept the Terms for free access' }),
    ).not.toBeInTheDocument();
    expect(redeem).toBeEnabled();
    fireEvent.click(redeem);
    await screen.findByText('Coupon redeemed');
    expect(billingService.redeemCoupon).toHaveBeenCalledWith(
      expect.objectContaining({
        termsVersion: null,
        acceptedTerms: false,
        approvedSpecificClauses: false,
      }),
    );
  });

  it('prevents duplicate confirmation and shows progress while redemption is unresolved', async () => {
    vi.mocked(billingService.redeemCoupon).mockReturnValue(new Promise(() => {}));
    renderPaywall();
    await reviewCoupon();
    const redeem = screen.getByRole('button', { name: 'Redeem coupon' });
    fireEvent.click(redeem);
    fireEvent.click(redeem);
    expect(screen.getByText('Confirming redemption…')).toHaveAttribute('role', 'status');
    expect(redeem).toBeDisabled();
    expect(billingService.redeemCoupon).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Check redemption' })).toBeDisabled();
  });

  it('looks up an uncertain result before retrying the same operation and revision', async () => {
    vi.mocked(billingService.redeemCoupon).mockRejectedValueOnce({ isAxiosError: true });
    vi.mocked(billingService.fetchCouponRedemption).mockRejectedValueOnce(
      apiError(404, 'Not found'),
    );
    renderPaywall();
    await reviewCoupon();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('not confirmed yet');
    const original = vi.mocked(billingService.redeemCoupon).mock.calls[0][0];
    expect(screen.getByRole('textbox', { name: 'Coupon code' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Check redemption' }));
    expect(await screen.findByText('Coupon redeemed')).toHaveFocus();
    expect(billingService.fetchCouponRedemption).toHaveBeenCalledWith(original.operationId);
    expect(billingService.redeemCoupon).toHaveBeenNthCalledWith(2, original);
    expect(sessionStorage.getItem(storageKey('coupon-redemption'))).toBeNull();
  });

  it('recovers a committed operation after remount without another confirmation', async () => {
    vi.mocked(billingService.redeemCoupon).mockRejectedValueOnce({ isAxiosError: true });
    const view = renderPaywall();
    await reviewCoupon();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    await screen.findByRole('alert');
    const original = vi.mocked(billingService.redeemCoupon).mock.calls[0][0];
    expect(sessionStorage.getItem(storageKey('coupon-redemption'))).not.toContain('private-code');
    view.unmount();
    vi.mocked(billingService.fetchCouponRedemption).mockResolvedValue(COUPON_RESULT);
    renderPaywall();
    expect(await screen.findByText('Coupon redeemed')).toHaveFocus();
    expect(billingService.fetchCouponRedemption).toHaveBeenCalledWith(original.operationId);
    expect(billingService.redeemCoupon).toHaveBeenCalledTimes(1);
  });

  it.each([401, 403, 429])(
    'keeps the original operation recoverable after HTTP %s',
    async (status) => {
      vi.mocked(billingService.redeemCoupon).mockRejectedValueOnce(apiError(status, 'Try again'));
      renderPaywall();
      await reviewCoupon();
      fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('not confirmed yet');
      const original = vi.mocked(billingService.redeemCoupon).mock.calls[0][0];
      expect(sessionStorage.getItem(storageKey('coupon-redemption'))).toContain(
        original.operationId,
      );
      vi.mocked(billingService.fetchCouponRedemption).mockResolvedValue(COUPON_RESULT);
      fireEvent.click(screen.getByRole('button', { name: 'Check redemption' }));
      expect(await screen.findByText('Coupon redeemed')).toHaveFocus();
      expect(billingService.redeemCoupon).toHaveBeenCalledTimes(1);
    },
  );

  it('releases a definitely refused operation and requires a fresh review', async () => {
    vi.mocked(billingService.redeemCoupon).mockResolvedValue({
      ...COUPON_RESULT,
      status: 'refused',
      detail: 'This subscription changed. Check the code again.',
    });
    renderPaywall();
    await reviewCoupon();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This subscription changed');
    expect(screen.queryByText('Coupon redeemed')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check redemption' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Coupon code' })).toHaveValue('private-code');
    expect(screen.getByRole('button', { name: 'Check code' })).toBeEnabled();
    expect(sessionStorage.getItem(storageKey('coupon-redemption'))).toBeNull();
  });

  it('requires fresh review after conflict and retains the code', async () => {
    vi.mocked(billingService.redeemCoupon).mockRejectedValueOnce(
      apiError(409, 'The offer changed. Check the code again.'),
    );
    renderPaywall();
    await reviewCoupon();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('offer changed');
    expect(screen.getByRole('textbox', { name: 'Coupon code' })).toHaveValue('private-code');
    expect(screen.queryByRole('button', { name: 'Redeem coupon' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check code' }));
    const fields = within(
      await screen.findByRole('group', { name: 'Accept the Terms for free access' }),
    );
    for (const box of fields.getAllByRole('checkbox')) expect(box).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Redeem coupon' })).toBeDisabled();
  });

  it('clears acceptance when changing language and links only cardless clauses in Italian', async () => {
    renderPaywall();
    await reviewCoupon();
    fireEvent.change(screen.getByRole('combobox', { name: 'Terms language' }), {
      target: { value: 'it' },
    });
    const fields = within(screen.getByRole('group', { name: 'Accept the Terms for free access' }));
    expect(fields.getByRole('link', { name: 'Termini' })).toHaveAttribute('href', '/it/terms');
    expect(fields.getByRole('link', { name: '21 (Foro competente)' })).toHaveAttribute(
      'href',
      '/it/terms#courts',
    );
    expect(fields.queryByText(/12|14-day/)).not.toBeInTheDocument();
    for (const box of fields.getAllByRole('checkbox')) {
      expect(box).not.toBeChecked();
      fireEvent.click(box);
    }
    expect(screen.getByText('Nessun pagamento automatico')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    await screen.findByText('Coupon redeemed');
    expect(billingService.redeemCoupon).toHaveBeenCalledWith(
      expect.objectContaining({ language: 'it' }),
    );
  });

  it('keeps the redeemed result available when refreshing Onboarding fails', async () => {
    renderPaywall();
    await reviewCoupon();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    await screen.findByText('Coupon redeemed');
    vi.mocked(onboardingService.fetchNextStep).mockRejectedValue(new Error('offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByText(/Couldn’t refresh your access/)).toBeInTheDocument();
    expect(screen.getByText('Coupon redeemed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });

  it('continues to Onboarding after redemption without choosing a paid plan', async () => {
    renderPaywall();
    await reviewCoupon();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    await screen.findByText('Coupon redeemed');
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('persona');
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(currentPath()).toBe('/onboarding'));
    expect(billingService.startSubscriptionCheckout).not.toHaveBeenCalled();
  });

  it('retains the code and restores focus after a transport error, then permits retry', async () => {
    vi.mocked(billingService.previewCoupon).mockRejectedValueOnce({ isAxiosError: true });
    renderPaywall();
    fireEvent.click(await screen.findByRole('button', { name: 'Have a coupon?' }));
    const input = screen.getByRole('textbox', { name: 'Coupon code' });
    fireEvent.change(input, { target: { value: 'private-retry-code' } });
    screen.getByRole('button', { name: 'Check code' }).focus();
    fireEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Couldn't check this coupon. Try again.",
    );
    expect(input).toHaveValue('private-retry-code');
    expect(input).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Check code' })).toBeEnabled();
  });

  it('keeps checking available when paid checkout is on hold and shows the eligibility refusal', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('unpaid'));
    vi.mocked(billingService.previewCoupon).mockRejectedValueOnce(
      apiError(409, 'Resolve your outstanding payment before using a coupon.'),
    );
    renderPaywall();
    fireEvent.click(await screen.findByRole('button', { name: 'Have a coupon?' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Coupon code' }), {
      target: { value: 'held-code' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Resolve your outstanding payment');
    expect(screen.getByRole('button', { name: 'Open billing portal' })).toBeInTheDocument();
  });

  it('announces checking and prevents repeated submission until the result arrives', async () => {
    vi.mocked(billingService.previewCoupon).mockReturnValue(new Promise(() => {}));
    renderPaywall();
    fireEvent.click(await screen.findByRole('button', { name: 'Have a coupon?' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Coupon code' }), {
      target: { value: 'pending-code' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Check code' }));
    expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Coupon code' })).toBeDisabled();
    expect(screen.getByText('Checking coupon…')).toHaveAttribute('role', 'status');
    expect(billingService.previewCoupon).toHaveBeenCalledTimes(1);
  });

  it('recovers the account pending coupon on the Paywall without browser storage or new coupon entry', async () => {
    vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...NOT_SUBSCRIBED,
      pendingCouponOperation: true,
      pendingCouponOperationId: 'ended-subscription-operation',
    });
    vi.mocked(billingService.fetchCouponRedemption).mockResolvedValue({
      ...COUPON_RESULT,
      status: 'pending',
    });
    renderPaywall();
    expect(await screen.findByText('Confirming redemption…')).toHaveAttribute('role', 'status');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Check redemption' })).toBeEnabled(),
    );
    expect(billingService.fetchCouponRedemption).toHaveBeenCalledWith(
      'ended-subscription-operation',
    );
    expect(screen.queryByRole('button', { name: 'Have a coupon?' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Start trial|Subscribe:|Open billing portal/ }),
    ).not.toBeInTheDocument();
    vi.mocked(billingService.fetchCouponRedemption).mockResolvedValue({
      ...COUPON_RESULT,
      status: 'completed',
    });
    fireEvent.click(screen.getByRole('button', { name: 'Check redemption' }));
    expect(await screen.findByText('Coupon redeemed')).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
    expect(billingService.redeemCoupon).not.toHaveBeenCalled();
    expect(billingService.startSubscriptionCheckout).not.toHaveBeenCalled();
  });

  it('removes paid checkout while a coupon submitted on the Paywall is pending', async () => {
    vi.mocked(billingService.redeemCoupon).mockResolvedValue({
      ...COUPON_RESULT,
      status: 'pending',
    });
    renderPaywall();
    await reviewCoupon();
    expect(screen.getByRole('button', { name: 'Start trial: Monthly' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Redeem coupon' }));
    expect(await screen.findByText('Confirming redemption…')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start trial: Monthly' })).not.toBeInTheDocument();
    expect(billingService.startSubscriptionCheckout).not.toHaveBeenCalled();
  });

  it('hides coupon entry when the feature is disabled', async () => {
    vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
    renderPaywall();
    await paywall();
    expect(screen.queryByRole('button', { name: 'Have a coupon?' })).not.toBeInTheDocument();
  });
});

describe('future signup recovery after free access expires', () => {
  beforeEach(() => {
    vi.mocked(billingService.fetchPlans).mockReset().mockResolvedValue(CATALOG);
    vi.mocked(billingService.startSubscriptionCheckout).mockReset();
    vi.mocked(billingService.fetchPaidSignup).mockReset();
    vi.mocked(onboardingService.fetchNextStep).mockReset().mockResolvedValue('paywall');
  });
  it('recovers account intent on the Paywall with coupons off before requesting fresh paid consent', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...NOT_SUBSCRIBED,
      trialDays: null,
      pendingPaidSignupId: 'expired-free-signup',
    });
    vi.mocked(billingService.fetchPaidSignup).mockResolvedValue({
      operationId: 'expired-free-signup',
      status: 'pending',
      detail: null,
      url: null,
      sessionId: 'cs_expired',
      firstPaymentAt: '2026-11-01T12:00:00Z',
      planKey: 'pumpkit_pro_monthly',
    });
    renderPaywall();
    const area = await paywall();
    expect(
      await area.findByRole('heading', { name: 'Confirm your future subscription' }),
    ).toBeInTheDocument();
    expect(await area.findByRole('button', { name: 'Check signup' })).toBeInTheDocument();
    expect(area.queryByRole('button', { name: /^Subscribe:/ })).not.toBeInTheDocument();
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...NOT_SUBSCRIBED,
      trialDays: null,
    });
    vi.mocked(billingService.fetchPaidSignup).mockResolvedValue({
      operationId: 'expired-free-signup',
      status: 'refused',
      detail: 'Review a fresh paid offer.',
      url: null,
      sessionId: 'cs_expired',
      firstPaymentAt: '2026-11-01T12:00:00Z',
      planKey: 'pumpkit_pro_monthly',
    });
    fireEvent.click(area.getByRole('button', { name: 'Check signup' }));
    expect(
      await area.findByRole('heading', { name: 'Subscribe to keep writing' }),
    ).toBeInTheDocument();
    expect(billingService.startSubscriptionCheckout).not.toHaveBeenCalled();
  });
});

describe('billing frequency recovery after free access expires', () => {
  const operation = {
    operationId: 'expired-free-plan-change',
    status: 'pending' as const,
    detail: 'Your earlier billing change is still being confirmed.',
    planKey: 'pumpkit_pro_yearly',
    productName: 'Pumpkit Pro',
    amount: 9000,
    currency: 'eur',
    interval: 'year',
    intervalCount: 1,
    firstPaymentAt: '2026-11-01T12:00:00Z',
  };
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(billingService.fetchPlanChange).mockReset().mockResolvedValue(operation);
    vi.mocked(billingService.startSubscriptionCheckout).mockReset();
    vi.mocked(onboardingService.fetchNextStep).mockReset().mockResolvedValue('paywall');
    vi.mocked(billingService.fetchBillingMe)
      .mockReset()
      .mockResolvedValue({
        ...NOT_SUBSCRIBED,
        pendingPlanChangeId: operation.operationId,
      });
  });

  it.each([true, false])(
    'keeps account recovery reachable with coupons enabled=%s',
    async (enabled) => {
      vi.mocked(billingService.fetchPlans)
        .mockReset()
        .mockResolvedValue({ ...CATALOG, couponsEnabled: enabled });
      renderSignedIn('/settings', { nextStep: 'paywall' });
      const area = await paywall();
      expect(
        await area.findByRole('heading', { name: 'Confirm your billing frequency change' }),
      ).toBeVisible();
      expect(await area.findByText(operation.detail)).toBeVisible();
      await waitFor(() =>
        expect(area.getByRole('button', { name: 'Check billing change' })).toBeEnabled(),
      );
      expect(currentPath()).toBe('/subscribe');
      expect(billingService.fetchPlanChange).toHaveBeenCalledWith(operation.operationId);
      expect(
        area.queryByRole('button', {
          name: /Subscribe:|Start trial:|Have a coupon|Open billing portal/,
        }),
      ).not.toBeInTheDocument();
      expect(area.queryByText(/Billing frequency changed\./)).not.toBeInTheDocument();

      vi.mocked(billingService.fetchPlanChange).mockRejectedValueOnce(apiError(503, 'Try again'));
      fireEvent.click(area.getByRole('button', { name: 'Check billing change' }));
      expect(await area.findByRole('alert')).toHaveTextContent('not confirmed yet');
      expect(area.getByRole('button', { name: 'Check billing change' })).toBeEnabled();
      expect(area.queryByRole('button', { name: /^Subscribe:/ })).not.toBeInTheDocument();
      expect(billingService.startSubscriptionCheckout).not.toHaveBeenCalled();
    },
  );

  it('refreshes a resolved refusal before offering a fresh subscription', async () => {
    vi.mocked(billingService.fetchPlans).mockReset().mockResolvedValue(CATALOG);
    renderPaywall();
    const area = await paywall();
    await area.findByText(operation.detail);
    await waitFor(() =>
      expect(area.getByRole('button', { name: 'Check billing change' })).toBeEnabled(),
    );
    vi.mocked(billingService.fetchPlanChange).mockImplementation(async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      return { ...operation, status: 'refused', detail: 'The change was not sent.' };
    });
    fireEvent.click(area.getByRole('button', { name: 'Check billing change' }));
    expect(await area.findByRole('heading', { name: 'Subscribe to keep writing' })).toBeVisible();
    expect(area.queryByText(/Billing frequency changed\./)).not.toBeInTheDocument();
    expect(billingService.startSubscriptionCheckout).not.toHaveBeenCalled();
  });
});
