import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';

vi.mock('@/services/userService', () => ({
  userService: {
    fetchProfile: vi.fn(),
    updateProfile: vi.fn(),
  },
}));
vi.mock('@/services/billingService', () => ({
  billingService: {
    previewPlanChange: vi.fn(),
    createPlanChange: vi.fn(),
    fetchPlanChange: vi.fn(),
    previewPaidSignup: vi.fn(),
    createPaidSignup: vi.fn(),
    fetchPaidSignup: vi.fn(),
    cancelPaidSignup: vi.fn(),
    previewCoupon: vi.fn(),
    redeemCoupon: vi.fn(),
    fetchCouponRedemption: vi.fn(),
    fetchBillingMe: vi.fn(),
    fetchPlans: vi.fn(),
    startSubscriptionCheckout: vi.fn(),
    startTopUpCheckout: vi.fn(),
    openBillingPortal: vi.fn(),
    subscribeNow: vi.fn(),
    cancelRenewal: vi.fn(),
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
    acceptPhoto: vi.fn(),
    declinePhoto: vi.fn(),
  },
}));
vi.mock('@/services/appConnectionService', () => ({
  appConnectionService: { list: vi.fn(), disconnect: vi.fn() },
}));
vi.mock('@/services/postService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/postService')>()),
  postService: {
    list: vi.fn().mockResolvedValue({
      posts: [],
      counts: { draft: 0, scheduled: 0, published: 0, failed: 0 },
      nextOffset: null,
    }),
  },
}));
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn().mockResolvedValue(null) },
}));
vi.mock('@/services/usageService', () => ({ usageService: { get: vi.fn() } }));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { SELLS_PLANS, WITH_OPERATOR } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { storageKey } from '@/lib/storage';
import { fireSuccessConfetti } from '@/lib/confetti';
import type { Instance } from '@/lib/instance';
import { redirectTo } from '@/lib/navigation';
import { appConnectionService } from '@/services/appConnectionService';
import { billingService, type BillingMe, type PlanCatalog } from '@/services/billingService';
import { usageService } from '@/services/usageService';
import { onboardingService } from '@/services/onboardingService';
import { userService, type UserProfile } from '@/services/userService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import {
  NOT_SUBSCRIBED,
  SUBSCRIBED,
  apiError,
  renderSignedIn,
  usageWith,
} from './testing/signedInApp';

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
  premium: false,
  needsReconnect: false,
  needsReconnectForMedia: false,
  scheduledPostsWaiting: 0,
  photoUrl: null,
  offerPhoto: false,
};

const X_PHOTO = 'https://pbs.twimg.com/profile_images/1/ada_200x200.jpg';
const X_PHOTO_DATA_URL = 'data:image/jpeg;base64,eA==';
const OFFERING_PHOTO: XConnection = { ...CONNECTED, photoUrl: X_PHOTO, offerPhoto: true };

const PERIOD_END = '2030-01-01T00:00:00Z';
const PERIOD_END_LABEL = new Date(PERIOD_END).toLocaleDateString(undefined, { dateStyle: 'long' });

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
  couponsEnabled: false,
  termsVersion: '2026-10-11',
  allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
  trial: { days: 7, generations: 125, xPosts: 25, linkXPosts: 2 },
  topUp: null,
};

const TOP_UP = { amount: 1000, currency: 'eur', generations: 250, xPosts: 50, linkXPosts: 5 };

function holding(
  status: NonNullable<BillingMe['subscription']>['status'],
  subscribed: boolean,
  cancelAt: string | null = null,
): BillingMe {
  return {
    subscription: {
      status,
      planKey: 'pumpkit_pro_monthly',
      currentPeriodEnd: PERIOD_END,
      cancelAt,
    },
    subscribed,
    maySubscribe: false,
    trialDays: null,
  };
}

const NO_PLANS: Instance = { ...SELLS_PLANS, sells_plans: false };

/** The element whose own text, across its children, reads `text`. */
function reading(text: string) {
  return (_: string, element: Element | null) =>
    element?.textContent === text &&
    Array.from(element.children).every((child) => child.textContent !== text);
}

function renderSettings(options: { state?: unknown; instance?: Instance } = {}) {
  return renderSignedIn('/settings', options);
}

function sidebarPhoto() {
  // An open dialog hides the rest of the page from the accessibility tree.
  return screen.getByRole('link', { name: /your account/i, hidden: true }).querySelector('img');
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
    vi.mocked(billingService.subscribeNow).mockReset();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(xConnectionService.startAuthorization).mockReset();
    vi.mocked(xConnectionService.disconnect).mockReset();
    vi.mocked(xConnectionService.acceptPhoto).mockReset();
    vi.mocked(xConnectionService.declinePhoto).mockReset().mockResolvedValue();
    vi.mocked(appConnectionService.list).mockReset().mockResolvedValue([]);
    vi.mocked(usageService.get).mockReset().mockResolvedValue(usageWith());
    vi.mocked(redirectTo).mockReset();
    vi.mocked(fireSuccessConfetti).mockReset();
    vi.mocked(track).mockClear();
  });

  it('shows Profile, X account, Plan, Usage and Connect AI apps to a Subscribed User', async () => {
    renderSettings();

    await card('Usage');
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Profile',
      'X account',
      'Plan',
      'Usage',
      'Connect AI apps',
    ]);
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
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

  describe('X photo offer', () => {
    it('asks a User offered the X photo whether to use it, showing it large', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(OFFERING_PHOTO);
      renderSettings();

      const dialog = await screen.findByRole('dialog', { name: 'Use your X photo?' });
      expect(dialog.querySelector('img')).toHaveAttribute('src', X_PHOTO);
      expect(
        within(dialog).getByText(
          'It will show next to your name in Pumpkit. You can change it in Settings.',
        ),
      ).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('x_photo_offer_shown');
    });

    it('asks nothing when the X connection offers no photo', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, photoUrl: X_PHOTO });
      renderSettings();

      await (await card('X account')).findByText('@ada');
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('uses the X photo, showing it in the sidebar at once', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(OFFERING_PHOTO);
      let finish: (profile: UserProfile) => void = () => {};
      vi.mocked(xConnectionService.acceptPhoto).mockReturnValue(
        new Promise((resolve) => (finish = resolve)),
      );
      renderSettings();

      const dialog = await screen.findByRole('dialog', { name: 'Use your X photo?' });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Use photo' }));

      expect(within(dialog).getByRole('button', { name: 'Using photo…' })).toBeDisabled();
      finish({ ...ADA, avatarUrl: X_PHOTO_DATA_URL });
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(sidebarPhoto()).toHaveAttribute('src', X_PHOTO_DATA_URL);
      expect(xConnectionService.declinePhoto).not.toHaveBeenCalled();
      expect(track).toHaveBeenCalledWith('x_photo_offer_accepted');
    });

    it('keeps the dialog open with an error line when the X photo cannot be used', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(OFFERING_PHOTO);
      vi.mocked(xConnectionService.acceptPhoto).mockRejectedValue(
        apiError(502, "Couldn't use your X photo. Try again."),
      );
      renderSettings();

      const dialog = await screen.findByRole('dialog', { name: 'Use your X photo?' });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Use photo' }));

      expect(await within(dialog).findByRole('alert')).toHaveTextContent(
        "Couldn't use your X photo. Try again.",
      );
      expect(within(dialog).getByRole('button', { name: 'Use photo' })).toBeEnabled();
      expect(sidebarPhoto()).toBeNull();
    });

    it.each([
      [
        'Not now',
        (dialog: HTMLElement) =>
          fireEvent.click(within(dialog).getByRole('button', { name: 'Not now' })),
      ],
      [
        'the close control',
        (dialog: HTMLElement) =>
          fireEvent.click(within(dialog).getByRole('button', { name: 'Close' })),
      ],
      ['Escape', (dialog: HTMLElement) => fireEvent.keyDown(dialog, { key: 'Escape' })],
    ])('declines the X photo with %s', async (_way, leave) => {
      vi.mocked(xConnectionService.get).mockResolvedValue(OFFERING_PHOTO);
      renderSettings();

      leave(await screen.findByRole('dialog', { name: 'Use your X photo?' }));

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(xConnectionService.declinePhoto).toHaveBeenCalledTimes(1);
      expect(xConnectionService.acceptPhoto).not.toHaveBeenCalled();
      expect(track).toHaveBeenCalledWith('x_photo_offer_declined');
    });
  });

  describe('Use photo from X', () => {
    it('switches the Photo to the X photo from the profile card', async () => {
      vi.mocked(userService.fetchProfile).mockResolvedValue({
        ...ADA,
        avatarUrl: 'data:image/png;base64,AAAA',
      });
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, photoUrl: X_PHOTO });
      vi.mocked(xConnectionService.acceptPhoto).mockResolvedValue({
        ...ADA,
        avatarUrl: X_PHOTO_DATA_URL,
      });
      renderSettings();

      const profile = await card('Profile');
      fireEvent.click(await profile.findByRole('button', { name: 'Use photo from X' }));

      await waitFor(() => expect(sidebarPhoto()).toHaveAttribute('src', X_PHOTO_DATA_URL));
      expect(
        profile.getByRole('button', { name: 'Change photo' }).querySelector('img'),
      ).toHaveAttribute('src', X_PHOTO_DATA_URL);
      expect(track).toHaveBeenCalledWith('account_x_photo_used');
    });

    it('shows why the X photo could not be used in the profile card', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, photoUrl: X_PHOTO });
      vi.mocked(xConnectionService.acceptPhoto).mockRejectedValue(apiError(502, 'X is down.'));
      renderSettings();

      const profile = await card('Profile');
      fireEvent.click(await profile.findByRole('button', { name: 'Use photo from X' }));

      expect(await profile.findByRole('alert')).toHaveTextContent(
        "Couldn't use your X photo. Try again.",
      );
    });

    it('is not offered without an X connection', async () => {
      renderSettings();

      const profile = await card('Profile');
      await profile.findByLabelText('First name');
      await (await card('X account')).findByRole('button', { name: 'Connect X' });
      expect(profile.queryByRole('button', { name: 'Use photo from X' })).not.toBeInTheDocument();
    });

    it('is not offered when the X account has no photo', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      renderSettings();

      const profile = await card('Profile');
      await (await card('X account')).findByText('@ada');
      expect(profile.queryByRole('button', { name: 'Use photo from X' })).not.toBeInTheDocument();
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
      expect(await dialog.findByText(/3 scheduled posts are waiting/)).toBeInTheDocument();
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

    it("shows the X account's photo beside its handle", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...CONNECTED,
        photoUrl: 'https://pbs.twimg.com/ada_200x200.jpg',
      });
      renderSettings();

      const x = await screen.findByRole('region', { name: 'X account' });
      await within(x).findByText('@ada');
      expect(x.querySelector('img')).toHaveAttribute(
        'src',
        'https://pbs.twimg.com/ada_200x200.jpg',
      );
    });

    it("shows the X account's initials when its photo fails to load", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...CONNECTED,
        photoUrl: 'https://pbs.twimg.com/gone.jpg',
      });
      renderSettings();

      const x = await screen.findByRole('region', { name: 'X account' });
      await within(x).findByText('@ada');
      fireEvent.error(x.querySelector('img')!);

      expect(x.querySelector('img')).toBeNull();
      expect(within(x).getByText('A')).toBeInTheDocument();
    });

    it('offers to reconnect X when the connection predates media', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...CONNECTED,
        needsReconnectForMedia: true,
      });
      vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
        'https://x.com/i/oauth2/authorize?state=s',
      );
      renderSettings();

      const x = await card('X account');
      expect(await x.findByText(/so Pumpkit can post media/)).toBeInTheDocument();
      fireEvent.click(x.getByRole('button', { name: 'Reconnect X' }));

      await waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
      );
    });

    it('asks to reconnect X once when its access is gone and it predates media', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...CONNECTED,
        needsReconnect: true,
        needsReconnectForMedia: true,
      });
      renderSettings();

      const x = await card('X account');
      expect(await x.findByText(/no longer accepts/)).toBeInTheDocument();
      expect(x.queryByText(/so Pumpkit can post media/)).not.toBeInTheDocument();
      expect(x.getAllByRole('button', { name: 'Reconnect X' })).toHaveLength(1);
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
  });

  describe('Plan', () => {
    it('lets a cardless free recipient buy a normal top-up with paid Terms', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
        subscription: null,
        subscribed: true,
        maySubscribe: false,
        trialDays: null,
        freeAccess: { startsAt: '2028-01-31T12:01:00Z', endsAt: '2028-04-30T12:01:00Z', months: 3 },
      });
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, topUp: TOP_UP });
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({ wayOut: 'top_up', mayBuyTopUp: true }),
      );
      renderSettings();
      const usage = await card('Usage');
      expect((await card('Plan')).getByText('No automatic payment')).toBeInTheDocument();
      fireEvent.click(await usage.findByRole('button', { name: 'Buy top-up, €10' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Buy a top-up' }));
      expect(dialog.getByText(/250 generations/)).toBeInTheDocument();
      expect(dialog.getAllByRole('checkbox')).toHaveLength(3);
      expect(usage.queryByRole('button', { name: 'Subscribe now' })).not.toBeInTheDocument();
    });

    it('shows cardless free access without renewal or paid signup controls', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
        subscription: null,
        subscribed: true,
        maySubscribe: false,
        trialDays: null,
        freeAccess: { startsAt: '2028-01-31T12:01:00Z', endsAt: '2028-04-30T12:01:00Z', months: 3 },
      });
      renderSettings();
      const plan = await card('Plan');
      expect(await plan.findByText('Free access')).toBeInTheDocument();
      expect(plan.getByText('No automatic payment')).toBeInTheDocument();
      expect(plan.getByText(/January 31, 2028 UTC to April 30, 2028 UTC/)).toBeInTheDocument();
      expect(plan.queryByRole('button')).not.toBeInTheDocument();
    });

    it.each([
      ['trialing', 'Trial', `Billing starts on ${PERIOD_END_LABEL}`],
      ['active', 'Active', `Renews on ${PERIOD_END_LABEL}`],
    ] as const)(
      'shows the Plan, a %s status as %s and when it next bills, with Manage subscription',
      async (status, label, nextBilling) => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding(status, true));
        renderSettings();

        const plan = await card('Plan');
        expect(await plan.findByText(label)).toBeInTheDocument();
        expect(plan.getByText('Pro')).toBeInTheDocument();
        expect(plan.getByText(nextBilling)).toBeInTheDocument();
        fireEvent.click(plan.getByRole('button', { name: 'Manage subscription' }));

        await waitFor(() =>
          expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'),
        );
      },
    );

    it.each(['trialing', 'active'] as const)(
      'says when a %s Subscription set to cancel ends, not when it would bill',
      async (status) => {
        const cancelAt = '2029-06-15T00:00:00Z';
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding(status, true, cancelAt));
        renderSettings();

        const plan = await card('Plan');
        expect(
          await plan.findByText(
            `Ends on ${new Date(cancelAt).toLocaleDateString(undefined, { dateStyle: 'long' })}`,
          ),
        ).toBeInTheDocument();
        expect(plan.queryByText(/Billing starts on|Renews on/)).not.toBeInTheDocument();
      },
    );

    it.each([
      ['past_due', true, 'Past due'],
      ['unpaid', false, 'Unpaid'],
    ] as const)(
      'warns that the last payment of a %s Subscription failed and offers Fix payment, with no renewal date',
      async (status, subscribed, label) => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding(status, subscribed));
        renderSettings();

        const plan = await card('Plan');
        expect(
          await plan.findByText('Your last payment failed. Update your card to keep access.'),
        ).toBeInTheDocument();
        expect(plan.getByText(label)).toBeInTheDocument();
        expect(plan.queryByText(/Renews on/)).not.toBeInTheDocument();
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
        "Couldn't load billing information.",
      );
    });
  });

  describe('Usage', () => {
    it('counts the generations, X posts and link posts left, and when they reset', async () => {
      renderSettings();

      const usageCard = await card('Usage');
      expect(await usageCard.findByText(reading('382 generations left'))).toBeInTheDocument();
      expect(usageCard.getByText(reading('61 X posts left, 8 of them with a link'))).toBeVisible();
      expect(usageCard.getByText('Resets on the 14th of each month')).toBeInTheDocument();
      expect(
        usageCard.getByText("Unused generations and X posts don't carry over."),
      ).toBeInTheDocument();
      expect(usageCard.getByRole('meter', { name: 'Generations left' })).toHaveAttribute(
        'aria-valuenow',
        '382',
      );
      expect(usageCard.getByRole('meter', { name: 'X posts left' })).toHaveAttribute(
        'aria-valuemax',
        '100',
      );
    });

    it.each([
      [1, 'Resets on the 1st of each month'],
      [22, 'Resets on the 22nd of each month'],
      [23, 'Resets on the 23rd of each month'],
      [11, 'Resets on the 11th of each month'],
      [29, 'Resets on the 29th of each month, or the last day of shorter months'],
      [31, 'Resets on the 31st of each month, or the last day of shorter months'],
    ])('says a period from day %i resets: "%s"', async (resetsOnDay, line) => {
      vi.mocked(usageService.get).mockResolvedValue(usageWith({ resetsOnDay }));
      renderSettings();

      expect(await (await card('Usage')).findByText(line)).toBeInTheDocument();
    });

    it('turns a bar to warning under 10% left and to destructive at 0', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({
          generations: { limit: 500, used: 457, left: 43 },
          xPosts: { limit: 100, used: 100, left: 0 },
          linkXPosts: { limit: 10, used: 10, left: 0 },
        }),
      );
      renderSettings();

      const usageCard = await card('Usage');
      const generations = await usageCard.findByRole('meter', { name: 'Generations left' });
      const xPosts = usageCard.getByRole('meter', { name: 'X posts left' });
      expect(generations.firstElementChild).toHaveClass('bg-warning');
      expect(xPosts.firstElementChild).toHaveClass('bg-destructive');
    });

    it('fills a bar in the primary color while 10% or more is left', async () => {
      renderSettings();

      const meter = await (await card('Usage')).findByRole('meter', { name: 'Generations left' });
      expect(meter.firstElementChild).toHaveClass('bg-primary');
    });

    it.each([
      ['About generations', 'Every prompt to generate or refine a post counts as one generation.'],
      [
        'About X posts',
        'Scheduled posts and posts you post now both count. For threads, each post in the thread counts.',
      ],
    ])('opens "%s" from its info button', async (button, explanation) => {
      renderSettings();

      fireEvent.click(await (await card('Usage')).findByRole('button', { name: button }));

      expect(await screen.findByText(explanation)).toBeInTheDocument();
    });

    it("counts a trial's allowance and says when the trial ends", async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('trialing', true));
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({
          trial: true,
          resetsAt: new Date('2026-11-07T09:00:00Z'),
          resetsOnDay: null,
          generations: { limit: 125, used: 27, left: 98 },
          xPosts: { limit: 25, used: 5, left: 20 },
          linkXPosts: { limit: 2, used: 0, left: 2 },
          wayOut: 'subscribe_now',
        }),
      );
      renderSettings();

      const usageCard = await card('Usage');
      expect(
        await usageCard.findByText(reading('98 of 125 generations left in your trial')),
      ).toBeInTheDocument();
      expect(
        usageCard.getByText(reading('20 of 25 X posts left in your trial, 2 of them with a link')),
      ).toBeInTheDocument();
      expect(usageCard.getByText('Your trial ends on 7 November')).toBeInTheDocument();
      expect(usageCard.queryByText(/Resets on/)).not.toBeInTheDocument();
    });

    describe('Subscribe now during a trial', () => {
      const TRIAL_USAGE = usageWith({
        trial: true,
        resetsAt: new Date('2026-11-07T09:00:00Z'),
        generations: { limit: 125, used: 125, left: 0 },
        xPosts: { limit: 25, used: 5, left: 20 },
        linkXPosts: { limit: 2, used: 0, left: 2 },
        wayOut: 'subscribe_now',
      });

      beforeEach(() => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('trialing', true));
        vi.mocked(usageService.get).mockResolvedValue(TRIAL_USAGE);
      });

      async function openDialog() {
        renderSettings();
        fireEvent.click(
          await (await card('Usage')).findByRole('button', { name: 'Subscribe now' }),
        );
        return within(await screen.findByRole('dialog'));
      }

      it("says the trial ends now and states the Plan's price and the monthly allowance", async () => {
        const dialog = await openDialog();

        expect(
          await dialog.findByText(
            "Your trial ends now and you're charged €9.00 today for your first month. Your monthly allowance of 500 generations and 100 X posts starts at once.",
          ),
        ).toBeInTheDocument();
      });

      it('names the interval of a yearly Plan', async () => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
          ...holding('trialing', true),
          subscription: {
            ...holding('trialing', true).subscription!,
            planKey: 'pumpkit_pro_yearly',
          },
        });
        const dialog = await openDialog();

        expect(
          await dialog.findByText(/you're charged €90\.00 today for your first year\./),
        ).toBeInTheDocument();
      });

      it('subscribes, says the monthly allowance has started and loads usage again', async () => {
        vi.mocked(billingService.subscribeNow).mockResolvedValue(holding('active', true));
        const dialog = await openDialog();
        vi.mocked(usageService.get).mockResolvedValue(usageWith());

        fireEvent.click(await dialog.findByRole('button', { name: 'Subscribe now' }));

        expect(
          await screen.findByText('Subscribed. Your monthly allowance has started.'),
        ).toBeInTheDocument();
        expect(billingService.subscribeNow).toHaveBeenCalledOnce();
        expect(track).toHaveBeenCalledWith('billing_subscribe_now_confirmed');
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(
          await (await card('Usage')).findByText(reading('382 generations left')),
        ).toBeInTheDocument();
      });

      it("shows the API's message when the first charge fails", async () => {
        vi.mocked(billingService.subscribeNow).mockRejectedValue(
          apiError(
            402,
            "Your trial has ended, but the first payment didn't go through. Open billing to complete or update your payment.",
          ),
        );
        const dialog = await openDialog();

        fireEvent.click(await dialog.findByRole('button', { name: 'Subscribe now' }));

        expect(
          await dialog.findByText(
            "Your trial has ended, but the first payment didn't go through. Open billing to complete or update your payment.",
          ),
        ).toBeInTheDocument();
        expect(track).not.toHaveBeenCalledWith('billing_subscribe_now_confirmed');
      });

      it('refreshes usage after a declined charge and keeps the payment error open', async () => {
        vi.mocked(billingService.subscribeNow).mockRejectedValue(
          apiError(402, "Your trial has ended, but the first payment didn't go through."),
        );
        renderSettings();
        const usageCard = await card('Usage');
        fireEvent.click(await usageCard.findByRole('button', { name: 'Subscribe now' }));
        const dialog = within(await screen.findByRole('dialog'));
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('past_due', true));
        vi.mocked(usageService.get).mockResolvedValue(
          usageWith({ wayOut: 'update_payment', mayBuyTopUp: false }),
        );

        fireEvent.click(await dialog.findByRole('button', { name: 'Subscribe now' }));

        expect(await usageCard.findByText(reading('382 generations left'))).toBeInTheDocument();
        expect(
          usageCard.getByRole('button', {
            name: 'Update your payment method to buy a top-up',
            hidden: true,
          }),
        ).toBeInTheDocument();
        expect(usageCard.queryByText(/Your trial ends/)).not.toBeInTheDocument();
        expect(
          usageCard.queryByRole('button', { name: 'Subscribe now', hidden: true }),
        ).not.toBeInTheDocument();
        expect(
          dialog.getByText("Your trial has ended, but the first payment didn't go through."),
        ).toBeInTheDocument();
        expect(track).not.toHaveBeenCalledWith('billing_subscribe_now_confirmed');
        fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      });

      it('links the invoice page when the first charge waits on the bank', async () => {
        vi.mocked(billingService.subscribeNow).mockRejectedValue(
          apiError(
            402,
            "Your trial has ended, but your bank needs you to confirm the first payment. Confirm it on Stripe's invoice page.",
            { code: 'PAYMENT_NEEDS_AUTHENTICATION', url: 'https://invoice.stripe.test/i/in_1' },
          ),
        );
        const dialog = await openDialog();
        vi.mocked(usageService.get).mockResolvedValue(
          usageWith({ wayOut: 'update_payment', mayBuyTopUp: false }),
        );

        fireEvent.click(await dialog.findByRole('button', { name: 'Subscribe now' }));

        const confirm = await dialog.findByRole('link', { name: 'Confirm payment' });
        await screen.findByText(reading('382 generations left'));
        expect(confirm).toBeInTheDocument();
        expect(confirm).toHaveAttribute('href', 'https://invoice.stripe.test/i/in_1');
        expect(confirm).toHaveAttribute('target', '_blank');
        expect(
          dialog.getByText(
            "Your trial has ended, but your bank needs you to confirm the first payment. Confirm it on Stripe's invoice page.",
          ),
        ).toBeInTheDocument();
        expect(dialog.queryByRole('button', { name: 'Subscribe now' })).not.toBeInTheDocument();
      });

      it('links no invoice page when the first charge is declined', async () => {
        vi.mocked(billingService.subscribeNow).mockRejectedValue(
          apiError(402, "Your trial has ended, but the first payment didn't go through.", {
            url: 'http://localhost:5173/billing',
          }),
        );
        const dialog = await openDialog();

        fireEvent.click(await dialog.findByRole('button', { name: 'Subscribe now' }));

        await dialog.findByText("Your trial has ended, but the first payment didn't go through.");
        expect(dialog.queryByRole('link', { name: 'Confirm payment' })).not.toBeInTheDocument();
      });

      it('closes on Cancel without subscribing', async () => {
        const dialog = await openDialog();

        fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }));

        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(billingService.subscribeNow).not.toHaveBeenCalled();
      });

      it('is not offered to a paid-up User', async () => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
        vi.mocked(usageService.get).mockResolvedValue(usageWith());
        renderSettings();

        const usageCard = await card('Usage');
        await usageCard.findByText(reading('382 generations left'));
        expect(usageCard.queryByRole('button', { name: 'Subscribe now' })).not.toBeInTheDocument();
      });
    });

    it('sends a User behind on payment to the billing portal to update their payment method', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('past_due', true));
      vi.mocked(usageService.get).mockResolvedValue(usageWith({ wayOut: 'update_payment' }));
      renderSettings();

      const usageCard = await card('Usage');
      fireEvent.click(
        await usageCard.findByRole('button', {
          name: 'Update your payment method to buy a top-up',
        }),
      );

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/x'));
    });

    it('shows what each top-up has left and until when, and offers to buy another', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, topUp: TOP_UP });
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({
          topUps: [
            {
              generationsLeft: 250,
              xPostsLeft: 50,
              linkXPostsLeft: 5,
              expiresAt: new Date('2027-10-03T08:00:00Z'),
            },
          ],
          mayBuyTopUp: true,
        }),
      );
      renderSettings();

      const usageCard = await card('Usage');
      expect(
        await usageCard.findByText(
          'Top-up: 250 generations and 50 X posts left, until 3 October 2027',
        ),
      ).toBeInTheDocument();
      fireEvent.click(await usageCard.findByRole('button', { name: 'Buy top-up, €10' }));
      expect(await screen.findByRole('dialog', { name: 'Buy a top-up' })).toBeInTheDocument();
    });

    it('leaves a count with no limit out of a top-up and its offer', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({
        ...CATALOG,
        topUp: { ...TOP_UP, generations: null },
      });
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({
          topUps: [
            {
              generationsLeft: null,
              xPostsLeft: 50,
              linkXPostsLeft: 5,
              expiresAt: new Date('2027-10-03T08:00:00Z'),
            },
          ],
          mayBuyTopUp: true,
        }),
      );
      renderSettings();

      const usageCard = await card('Usage');
      expect(
        await usageCard.findByText('Top-up: 50 X posts left, until 3 October 2027'),
      ).toBeInTheDocument();
      fireEvent.click(await usageCard.findByRole('button', { name: 'Buy top-up, €10' }));
      const dialog = await screen.findByRole('dialog', { name: 'Buy a top-up' });
      expect(within(dialog).getByText(/^50 X posts, up to 5 with a link, for €10\./)).toBeVisible();
    });

    it('offers only Buy top-up while no top-up has anything left', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, topUp: TOP_UP });
      vi.mocked(usageService.get).mockResolvedValue(usageWith({ mayBuyTopUp: true }));
      renderSettings();

      const usageCard = await card('Usage');
      expect(await usageCard.findByRole('button', { name: 'Buy top-up, €10' })).toBeVisible();
      expect(usageCard.queryByText(/^Top-up:/)).not.toBeInTheDocument();
    });

    it('offers no top-up to a User who may not buy one', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, topUp: TOP_UP });
      renderSettings();

      const usageCard = await card('Usage');
      await usageCard.findByText(reading('382 generations left'));
      expect(usageCard.queryByRole('button', { name: /Buy top-up/ })).not.toBeInTheDocument();
    });

    it('greets a bought top-up and shows it once usage loads again after a short wait', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, topUp: TOP_UP });
      // Stripe tells Pumpkit about the top-up only after Settings first loads usage.
      vi.mocked(usageService.get)
        .mockResolvedValueOnce(usageWith({ mayBuyTopUp: true }))
        .mockResolvedValue(
          usageWith({
            topUps: [
              {
                generationsLeft: 250,
                xPostsLeft: 50,
                linkXPostsLeft: 5,
                expiresAt: new Date('2027-10-03T08:00:00Z'),
              },
            ],
            mayBuyTopUp: true,
          }),
        );
      vi.useFakeTimers({ shouldAdvanceTime: true });
      onTestFinished(() => {
        vi.useRealTimers();
      });
      renderSettings({ state: { checkoutStatus: 'top_up_bought' } });

      const usageCard = await card('Usage');
      expect(await usageCard.findByRole('button', { name: 'Buy top-up, €10' })).toBeVisible();
      expect(usageCard.queryByText(/^Top-up:/)).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('top_up_bought');
      expect(
        await screen.findByText('Top-up added: 250 generations and 50 X posts.'),
      ).toBeInTheDocument();
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(
        await usageCard.findByText(/^Top-up: 250 generations and 50 X posts left/),
      ).toBeInTheDocument();
    });

    it('leaves a count with no limit out of the greeting for a bought top-up', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({
        ...CATALOG,
        topUp: { ...TOP_UP, generations: null },
      });
      renderSettings({ state: { checkoutStatus: 'top_up_bought' } });

      expect(await screen.findByText('Top-up added: 50 X posts.')).toBeInTheDocument();
    });

    it('says nothing about a limit set to no cap', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({
          generations: { limit: null, used: 7, left: null },
          linkXPosts: { limit: null, used: 1, left: null },
        }),
      );
      renderSettings();

      const usageCard = await card('Usage');
      expect(await usageCard.findByText(reading('61 X posts left'))).toBeInTheDocument();
      expect(usageCard.queryByText(/generations left/)).not.toBeInTheDocument();
      expect(usageCard.queryByRole('meter', { name: 'Generations left' })).not.toBeInTheDocument();
    });

    it('shows a placeholder while usage loads', async () => {
      vi.mocked(usageService.get).mockReturnValue(new Promise(() => undefined));
      renderSettings();

      expect(await (await card('Usage')).findByRole('status')).toHaveTextContent(
        'Loading your usage…',
      );
    });

    it('says when usage could not be loaded', async () => {
      vi.mocked(usageService.get).mockRejectedValue(apiError(500, 'boom'));
      renderSettings();

      expect(await (await card('Usage')).findByRole('alert')).toHaveTextContent(
        "Couldn't load your usage. Reload the page to try again.",
      );
    });

    it('is not shown to a User who is not Subscribed', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderSettings();

      await card('Plan');
      expect(screen.queryByRole('region', { name: 'Usage' })).not.toBeInTheDocument();
    });
  });

  describe('On an Instance that sells no Plans', () => {
    it('shows no Plan card and asks nothing about billing', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderSettings({ instance: NO_PLANS });

      await card('Profile');
      expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
        'Profile',
        'X account',
        'Connect AI apps',
      ]);
      expect(
        await (await card('X account')).findByRole('button', { name: 'Connect X' }),
      ).toBeInTheDocument();
      expect(billingService.fetchBillingMe).not.toHaveBeenCalled();
      expect(usageService.get).not.toHaveBeenCalled();
    });
  });

  describe('On an Instance without X', () => {
    it('shows no X account card and no way to connect X', async () => {
      renderSettings({ instance: { ...SELLS_PLANS, x_connection: false } });

      await card('Profile');
      expect(screen.queryByRole('region', { name: 'X account' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Connect X' })).not.toBeInTheDocument();
    });
  });

  it('has no theme selector while dark mode is enforced', async () => {
    renderSettings();
    await card('Profile');
    expect(screen.queryByRole('region', { name: 'Appearance' })).not.toBeInTheDocument();
    expect(document.documentElement).toHaveClass('dark');
  });

  describe('Footer', () => {
    const ANALYTICS = {
      key: 'phc_test',
      host: 'https://eu.i.posthog.com',
      ui_host: 'https://eu.posthog.com',
    };

    it('links to the company details, the Privacy Policy and the Terms in a new tab', async () => {
      renderSettings({ instance: WITH_OPERATOR });

      const legal = within(await screen.findByRole('navigation', { name: 'Legal' }));
      const company = legal.getByRole('link', { name: 'Company details' });
      const privacy = legal.getByRole('link', { name: 'Privacy Policy' });
      const terms = legal.getByRole('link', { name: 'Terms' });
      expect(company).toHaveAttribute('href', '/terms#operator');
      expect(privacy).toHaveAttribute('href', '/privacy');
      expect(terms).toHaveAttribute('href', '/terms');
      for (const link of [company, privacy, terms]) {
        expect(link).toHaveAttribute('target', '_blank');
      }
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

it('redeems another coupon in Settings and refreshes the Plan and current Usage', async () => {
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  sessionStorage.clear();
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, couponsEnabled: true });
  const free = {
    ...SUBSCRIBED,
    subscription: null,
    freeAccess: { startsAt: '2028-01-31T12:00:00Z', endsAt: '2028-02-29T12:00:00Z', months: 1 },
  };
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(free);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.previewCoupon).mockResolvedValue({
    months: 1,
    startsAt: '2028-02-29T12:00:00Z',
    endsAt: '2028-03-31T12:00:00Z',
    allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
    nextPaymentAt: null,
    termsVersion: null,
    revision: 'settings-preview',
  });
  vi.mocked(billingService.redeemCoupon).mockImplementation(async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...free,
      freeAccess: {
        ...free.freeAccess,
        endsAt: '2028-03-31T12:00:00Z',
        months: 2,
        currentStartsAt: '2028-01-31T12:00:00Z',
        currentEndsAt: '2028-02-29T12:00:00Z',
        queuedStartsAt: '2028-02-29T12:00:00Z',
      },
    });
    return {
      operationId: 'settings-operation',
      startsAt: '2028-02-29T12:00:00Z',
      endsAt: '2028-03-31T12:00:00Z',
      months: 1,
    };
  });
  renderSettings();
  const plan = await card('Plan');
  fireEvent.click(await plan.findByRole('button', { name: 'Redeem coupon' }));
  const input = plan.getByRole('textbox', { name: 'Coupon code' });
  expect(input).toHaveFocus();
  expect(plan.getByRole('button', { name: 'Check code' })).toBeDisabled();
  fireEvent.change(input, { target: { value: 'private-settings-code' } });
  fireEvent.click(plan.getByRole('button', { name: 'Check code' }));
  const preview = await plan.findByRole('status', { name: 'Coupon preview' });
  expect(preview).toHaveFocus();
  expect(within(preview).getByText('Starts')).toBeInTheDocument();
  const reads = vi.mocked(usageService.get).mock.calls.length;
  fireEvent.click(within(preview).getByRole('button', { name: 'Redeem coupon' }));
  expect(await plan.findByText('Coupon redeemed')).toHaveFocus();
  await waitFor(() =>
    expect(plan.getByText(/Free access through/)).toHaveTextContent('March 31, 2028'),
  );
  await waitFor(() => expect(vi.mocked(usageService.get).mock.calls.length).toBeGreaterThan(reads));
  expect(plan.getByText(/Current free access:/)).toHaveTextContent('February 29, 2028');
  expect(plan.getByText(/Queued free access:/)).toHaveTextContent('March 31, 2028');
  expect(plan.getByText(/creates no subscription/)).toBeInTheDocument();
  fireEvent.click(plan.getByRole('button', { name: 'Redeem another coupon' }));
  await waitFor(() => expect(plan.getByRole('textbox', { name: 'Coupon code' })).toHaveFocus());
  expect(plan.getByRole('textbox', { name: 'Coupon code' })).toHaveValue('');
  expect(plan.getByRole('button', { name: 'Check code' })).toBeDisabled();
});

it('confirms a monthly coupon safely after reload and shows paid time and deferred renewal', async () => {
  vi.mocked(billingService.redeemCoupon).mockClear();
  vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
  sessionStorage.clear();
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, couponsEnabled: true });
  const monthly = holding('active', true);
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(monthly);
  vi.mocked(billingService.previewCoupon).mockResolvedValue({
    months: 1,
    startsAt: '2028-02-29T12:00:00Z',
    endsAt: '2028-03-31T12:00:00Z',
    allowance: CATALOG.allowance,
    nextPaymentAt: '2028-03-31T12:00:00Z',
    termsVersion: null,
    revision: 'monthly-preview',
  });
  const accepted = {
    operationId: 'monthly-operation',
    months: 1,
    startsAt: '2028-02-29T12:00:00Z',
    endsAt: '2028-03-31T12:00:00Z',
    nextPaymentAt: '2028-03-31T12:00:00Z',
  };
  vi.mocked(billingService.redeemCoupon).mockResolvedValue({ ...accepted, status: 'pending' });
  const view = renderSettings();
  let plan = await card('Plan');
  fireEvent.click(plan.getByRole('button', { name: 'Redeem coupon' }));
  fireEvent.change(plan.getByRole('textbox', { name: 'Coupon code' }), {
    target: { value: 'private-monthly-code' },
  });
  fireEvent.click(plan.getByRole('button', { name: 'Check code' }));
  const preview = await plan.findByRole('status', { name: 'Coupon preview' });
  expect(within(preview).getByText(/Next payment:/)).toHaveTextContent('Mar 31, 2028 UTC');
  expect(within(preview).queryByText(/no subscription or obligation/)).not.toBeInTheDocument();
  fireEvent.click(within(preview).getByRole('button', { name: 'Redeem coupon' }));
  expect(await plan.findByText('Confirming redemption…')).toHaveAttribute('role', 'status');
  await waitFor(() => expect(plan.getByRole('button', { name: 'Check redemption' })).toBeEnabled());
  expect(plan.queryByText('Coupon redeemed')).not.toBeInTheDocument();
  expect(plan.getByRole('button', { name: 'Manage billing' })).toBeDisabled();
  expect(sessionStorage.getItem(storageKey('coupon-redemption'))).toContain('monthly-preview');
  expect(plan.getByRole('textbox', { name: 'Coupon code' })).toBeDisabled();
  view.unmount();
  vi.mocked(billingService.fetchCouponRedemption).mockResolvedValue({
    ...accepted,
    status: 'completed',
  });
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
    ...monthly,
    couponDeferral: true,
    pendingCouponOperation: false,
    subscription: {
      ...monthly.subscription!,
      status: 'trialing',
      currentPeriodEnd: accepted.endsAt,
      paidThrough: accepted.startsAt,
    },
    freeAccess: {
      startsAt: accepted.startsAt,
      endsAt: accepted.endsAt,
      months: 1,
      currentStartsAt: null,
      currentEndsAt: null,
      queuedStartsAt: accepted.startsAt,
    },
  });
  renderSettings();
  plan = await card('Plan');
  expect(await plan.findByText('Coupon redeemed')).toHaveFocus();
  expect(plan.getByText(/Paid access through/)).toHaveTextContent('February 29, 2028 UTC');
  expect(plan.getByText(/Queued free access:/)).toHaveTextContent('March 31, 2028 UTC');
  expect(plan.queryByText(/Current free access:/)).not.toBeInTheDocument();
  expect(plan.getAllByText(/Next payment:/)).toHaveLength(2);
  expect(plan.queryByText('Trial')).not.toBeInTheDocument();
  expect(plan.queryByText('No automatic payment')).not.toBeInTheDocument();
  expect(plan.getByRole('button', { name: 'Manage billing' })).toBeEnabled();
  expect(plan.getByRole('button', { name: 'Cancel renewal' })).toBeEnabled();
  expect(billingService.redeemCoupon).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem(storageKey('coupon-redemption'))).toBeNull();
});

it('recovers the account pending operation without browser storage while new coupons are disabled', async () => {
  sessionStorage.clear();
  vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
    ...holding('active', true),
    pendingCouponOperation: true,
    pendingCouponOperationId: 'recover-from-account',
    subscription: { ...holding('trialing', true).subscription! },
  });
  const result = {
    operationId: 'recover-from-account',
    months: 1,
    startsAt: '2028-02-29T12:00:00Z',
    endsAt: '2028-03-31T12:00:00Z',
    nextPaymentAt: '2028-03-31T12:00:00Z',
  };
  vi.mocked(billingService.fetchCouponRedemption)
    .mockReset()
    .mockResolvedValue({
      ...result,
      status: 'pending',
    });
  vi.mocked(billingService.redeemCoupon).mockClear();
  renderSettings();
  const plan = await card('Plan');
  expect(await plan.findByText('Confirming redemption…')).toBeInTheDocument();
  await waitFor(() => expect(plan.getByRole('button', { name: 'Check redemption' })).toBeEnabled());
  expect(billingService.fetchCouponRedemption).toHaveBeenCalledWith('recover-from-account');
  expect(plan.getByText('Confirming coupon')).toBeInTheDocument();
  expect(plan.queryByText('Trial')).not.toBeInTheDocument();
  expect(plan.queryByRole('button', { name: 'Redeem coupon' })).not.toBeInTheDocument();
  expect(plan.getByRole('button', { name: 'Manage subscription' })).toBeDisabled();
  vi.mocked(billingService.fetchCouponRedemption).mockResolvedValue({
    ...result,
    status: 'completed',
  });
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('active', true));
  fireEvent.click(plan.getByRole('button', { name: 'Check redemption' }));
  await waitFor(() =>
    expect(plan.getByRole('button', { name: 'Manage subscription' })).toBeEnabled(),
  );
  expect(billingService.redeemCoupon).not.toHaveBeenCalled();
});

it('retries cancellation safely and keeps the paid and queued free dates', async () => {
  sessionStorage.clear();
  vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
  const monthly: BillingMe = {
    ...holding('trialing', true),
    couponDeferral: true,
    subscription: {
      ...holding('trialing', true).subscription!,
      paidThrough: '2028-02-29T12:00:00Z',
      currentPeriodEnd: '2028-03-31T12:00:00Z',
    },
    freeAccess: {
      months: 1,
      startsAt: '2028-02-29T12:00:00Z',
      endsAt: '2028-03-31T12:00:00Z',
      currentStartsAt: null,
      currentEndsAt: null,
      queuedStartsAt: '2028-02-29T12:00:00Z',
    },
  };
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(monthly);
  vi.mocked(billingService.cancelRenewal)
    .mockReset()
    .mockRejectedValueOnce(apiError(502, 'Try again'));
  renderSettings();
  const plan = await card('Plan');
  fireEvent.click(await plan.findByRole('button', { name: 'Cancel renewal' }));
  expect(await plan.findByRole('alert')).toHaveTextContent('Try again');
  vi.mocked(billingService.cancelRenewal).mockImplementation(async () => {
    const canceled = {
      ...monthly,
      subscription: { ...monthly.subscription!, cancelAt: '2028-03-31T12:00:00Z' },
    };
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(canceled);
    return canceled;
  });
  fireEvent.click(plan.getByRole('button', { name: 'Cancel renewal' }));
  expect(await plan.findByText(/Ends on/)).toHaveTextContent('March 31, 2028');
  expect(plan.getByText(/Renewal cancelled/)).toHaveFocus();
  expect(plan.getByText('No automatic payment')).toBeInTheDocument();
  expect(plan.getByText(/Paid access through/)).toHaveTextContent('February 29, 2028 UTC');
  expect(plan.getByText(/Queued free access:/)).toHaveTextContent('March 31, 2028 UTC');
  expect(plan.queryByRole('button', { name: 'Cancel renewal' })).not.toBeInTheDocument();
  expect(billingService.cancelRenewal).toHaveBeenCalledTimes(2);
});

it.each(['2028-02-10T12:00:00Z', null])(
  'shows earned coverage and no payment after provider cancellation at %s',
  async (cancelAt) => {
    vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
    vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
    vi.mocked(appConnectionService.list).mockResolvedValue([]);
    vi.mocked(usageService.get).mockResolvedValue(usageWith());
    vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...holding('canceled', true),
      couponDeferral: true,
      subscription: {
        ...holding('canceled', true).subscription!,
        cancelAt,
        paidThrough: '2028-02-29T12:00:00Z',
      },
      freeAccess: {
        months: 1,
        startsAt: '2028-02-29T12:00:00Z',
        endsAt: '2028-03-31T12:00:00Z',
        currentStartsAt: null,
        currentEndsAt: null,
        queuedStartsAt: '2028-02-29T12:00:00Z',
      },
    });
    renderSettings();
    const plan = await card('Plan');
    expect(await plan.findByText(/Ends on/)).toHaveTextContent('March 31, 2028');
    expect(plan.getByText('No automatic payment')).toBeInTheDocument();
    expect(plan.queryByRole('button', { name: 'Cancel renewal' })).not.toBeInTheDocument();
    expect(plan.queryByText(/Next payment:/)).not.toBeInTheDocument();
  },
);

it('distinguishes the original introductory trial from queued full free access and payment', async () => {
  vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
    ...holding('trialing', true),
    couponDeferral: true,
    subscription: {
      ...holding('trialing', true).subscription!,
      introductoryTrialEnd: '2028-01-31T12:00:00Z',
      currentPeriodEnd: '2028-03-31T12:00:00Z',
    },
    freeAccess: {
      months: 2,
      startsAt: '2028-01-31T12:00:00Z',
      endsAt: '2028-03-31T12:00:00Z',
      currentStartsAt: null,
      currentEndsAt: null,
      queuedStartsAt: '2028-01-31T12:00:00Z',
    },
  });
  renderSettings();
  const plan = await card('Plan');
  expect(await plan.findByText(/Introductory trial through/)).toHaveTextContent(
    'January 31, 2028 UTC',
  );
  expect(plan.queryByText(/Paid access through/)).not.toBeInTheDocument();
  expect(plan.getByText(/Queued free access:/)).toHaveTextContent('January 31, 2028 UTC');
  expect(plan.getByText(/Next payment:/)).toHaveTextContent('March 31, 2028 UTC');
  expect(plan.queryByRole('button', { name: 'Subscribe now' })).not.toBeInTheDocument();
  expect(plan.getByRole('button', { name: 'Cancel renewal' })).toBeEnabled();
});

it.each(['month', 'year', 'same-day'])(
  'reviews the exact future %s offer before separate paid acceptance',
  async (scenario) => {
    const interval = scenario === 'same-day' ? 'month' : scenario;
    const firstPaymentAt =
      scenario === 'same-day'
        ? new Date().toISOString().slice(0, 10) + 'T23:59:59Z'
        : '2028-03-31T12:00:00Z';
    sessionStorage.clear();
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
    vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
    vi.mocked(appConnectionService.list).mockResolvedValue([]);
    vi.mocked(usageService.get).mockResolvedValue(usageWith());
    vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, couponsEnabled: true });
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...SUBSCRIBED,
      subscription: null,
      mayArrangePaidSignup: true,
      freeAccess: { startsAt: '2028-01-31T12:00:00Z', endsAt: '2028-03-31T12:00:00Z', months: 2 },
    });
    const planKey = interval === 'month' ? 'pumpkit_pro_monthly' : 'pumpkit_pro_yearly';
    vi.mocked(billingService.previewPaidSignup).mockResolvedValue({
      planKey,
      productName: 'Pro',
      amount: interval === 'month' ? 900 : 9000,
      currency: 'eur',
      interval,
      intervalCount: 1,
      firstPaymentAt,
      termsVersion: '2026-11-08',
      revision: 'future-offer',
    });
    vi.mocked(billingService.createPaidSignup).mockClear().mockResolvedValue({
      operationId: 'accepted-signup',
      status: 'pending',
      detail: null,
      url: 'https://checkout.stripe.test/setup',
      sessionId: 'cs_setup',
      firstPaymentAt,
      planKey,
    });
    vi.mocked(redirectTo).mockClear();
    renderSettings();
    const plan = await card('Plan');
    fireEvent.click(await plan.findByRole('button', { name: 'Arrange subscription' }));
    fireEvent.click(
      plan.getByRole('button', {
        name: interval === 'month' ? 'Review monthly plan' : 'Review yearly plan',
      }),
    );
    const offer = await plan.findByRole('region', { name: 'Review future subscription' });
    if (scenario === 'same-day') {
      expect(offer).toHaveTextContent('23:59:59 UTC');
    } else {
      expect(offer).toHaveTextContent('March 31, 2028');
      expect(offer).toHaveTextContent('12:00:00 UTC');
    }
    expect(offer).toHaveTextContent('No immediate payment');
    expect(offer).not.toHaveTextContent('No payment today');
    const confirm = within(offer).getByRole('button', { name: 'Agree and continue to checkout' });
    expect(confirm).toBeDisabled();
    expect(billingService.createPaidSignup).not.toHaveBeenCalled();
    for (const box of within(offer).getAllByRole('checkbox')) fireEvent.click(box);
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(redirectTo).toHaveBeenCalledWith('https://checkout.stripe.test/setup'),
    );
    expect(billingService.createPaidSignup).toHaveBeenLastCalledWith(
      expect.objectContaining({
        revision: 'future-offer',
        termsVersion: '2026-11-08',
        acceptedTerms: true,
        requestedImmediateStart: true,
        approvedSpecificClauses: true,
        language: 'en',
      }),
    );
    expect(sessionStorage.getItem(storageKey('paid-signup'))).toContain('future-offer');
  },
);

it('recovers a future signup from the account with coupons off, then confirms without new consent or checkout', async () => {
  sessionStorage.clear();
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
  const free = { startsAt: '2028-01-31T12:00:00Z', endsAt: '2028-03-31T12:00:00Z', months: 2 };
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
    ...SUBSCRIBED,
    subscription: null,
    pendingPaidSignupId: 'account-signup',
    freeAccess: free,
  });
  vi.mocked(billingService.fetchPaidSignup)
    .mockReset()
    .mockResolvedValueOnce({
      operationId: 'account-signup',
      status: 'pending',
      detail: null,
      url: null,
      sessionId: null,
      firstPaymentAt: free.endsAt,
      planKey: 'pumpkit_pro_monthly',
    })
    .mockImplementation(async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
        ...SUBSCRIBED,
        couponDeferral: true,
        pendingPaidSignupId: null,
        freeAccess: free,
        subscription: {
          status: 'trialing',
          planKey: 'pumpkit_pro_monthly',
          currentPeriodEnd: free.endsAt,
          cancelAt: null,
        },
      });
      return {
        operationId: 'account-signup',
        status: 'completed',
        detail: null,
        url: null,
        sessionId: 'cs_setup',
        firstPaymentAt: free.endsAt,
        planKey: 'pumpkit_pro_monthly',
      };
    });
  vi.mocked(billingService.createPaidSignup).mockClear();
  renderSettings();
  const plan = await card('Plan');
  await waitFor(() => expect(plan.getByRole('button', { name: 'Check signup' })).toBeEnabled());
  expect(plan.getByText(/future subscription is not confirmed yet/i)).toBeInTheDocument();
  expect(plan.queryByText('No automatic payment')).not.toBeInTheDocument();
  expect(plan.queryByRole('button', { name: 'Arrange subscription' })).not.toBeInTheDocument();
  expect(plan.queryByRole('button', { name: 'Redeem coupon' })).not.toBeInTheDocument();
  fireEvent.click(plan.getByRole('button', { name: 'Check signup' }));
  expect(
    await plan.findByText(/Subscription arranged\. Your free access stays unchanged/),
  ).toBeInTheDocument();
  expect(await plan.findByText('Next payment: March 31, 2028 UTC')).toBeInTheDocument();
  expect(plan.getByRole('button', { name: 'Cancel renewal' })).toBeEnabled();
  expect(billingService.createPaidSignup).not.toHaveBeenCalled();
});

it('keeps an interrupted signup recoverable and cancellation preserves free access', async () => {
  sessionStorage.clear();
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
  const free = { startsAt: '2028-01-31T12:00:00Z', endsAt: '2028-03-31T12:00:00Z', months: 2 };
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
    ...SUBSCRIBED,
    subscription: null,
    pendingPaidSignupId: 'cancel-signup',
    freeAccess: free,
  });
  vi.mocked(billingService.fetchPaidSignup).mockReset().mockRejectedValue(new Error('network'));
  vi.mocked(billingService.cancelPaidSignup)
    .mockReset()
    .mockImplementation(async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
        ...SUBSCRIBED,
        subscription: null,
        freeAccess: free,
      });
      return {
        operationId: 'cancel-signup',
        status: 'refused',
        detail: 'Signup cancelled. Your free access is unchanged.',
        url: null,
        sessionId: null,
        firstPaymentAt: free.endsAt,
        planKey: 'pumpkit_pro_monthly',
      };
    });
  renderSettings();
  const plan = await card('Plan');
  expect(await plan.findByText(/Check signup to retrieve its result safely/)).toBeInTheDocument();
  fireEvent.click(plan.getByRole('button', { name: 'Cancel signup' }));
  expect(
    await plan.findByText('Signup cancelled. Your free access is unchanged.'),
  ).toBeInTheDocument();
  expect(billingService.cancelPaidSignup).toHaveBeenCalledWith('cancel-signup');
  expect(plan.getByText('Free access through March 31, 2028 UTC')).toBeInTheDocument();
  expect(plan.getByText('No automatic payment')).toBeInTheDocument();
});

it('requires a fresh reviewed offer after a changed date and omits legal boxes without Terms', async () => {
  sessionStorage.clear();
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue({
    ...CATALOG,
    couponsEnabled: true,
    termsVersion: null,
  });
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
    ...SUBSCRIBED,
    subscription: null,
    mayArrangePaidSignup: true,
    freeAccess: { startsAt: '2028-01-31T12:00:00Z', endsAt: '2028-03-31T12:00:00Z', months: 2 },
  });
  vi.mocked(billingService.previewPaidSignup).mockReset().mockResolvedValue({
    planKey: 'pumpkit_pro_monthly',
    productName: 'Pro',
    amount: 900,
    currency: 'eur',
    interval: 'month',
    intervalCount: 1,
    firstPaymentAt: '2028-03-31T12:00:00Z',
    termsVersion: null,
    revision: 'old-date',
  });
  vi.mocked(billingService.createPaidSignup)
    .mockReset()
    .mockRejectedValue(apiError(409, 'The payment date has changed. Review it again.'));
  renderSettings();
  const plan = await card('Plan');
  fireEvent.click(await plan.findByRole('button', { name: 'Arrange subscription' }));
  fireEvent.click(plan.getByRole('button', { name: 'Review monthly plan' }));
  const offer = await plan.findByRole('region', { name: 'Review future subscription' });
  expect(within(offer).queryByRole('checkbox')).not.toBeInTheDocument();
  fireEvent.click(within(offer).getByRole('button', { name: 'Agree and continue to checkout' }));
  expect(
    await plan.findByText('The payment date has changed. Review it again.'),
  ).toBeInTheDocument();
  expect(
    plan.queryByRole('region', { name: 'Review future subscription' }),
  ).not.toBeInTheDocument();
  expect(sessionStorage.getItem(storageKey('paid-signup'))).toBeNull();
  vi.mocked(billingService.previewPaidSignup).mockResolvedValue({
    planKey: 'pumpkit_pro_monthly',
    productName: 'Pro',
    amount: 900,
    currency: 'eur',
    interval: 'month',
    intervalCount: 1,
    firstPaymentAt: '2028-04-30T12:00:00Z',
    termsVersion: null,
    revision: 'new-date',
  });
  fireEvent.click(plan.getByRole('button', { name: 'Review monthly plan' }));
  expect(await plan.findByRole('region', { name: 'Review future subscription' })).toHaveTextContent(
    'April 30, 2028',
  );
  expect(billingService.createPaidSignup).toHaveBeenCalledTimes(1);
});

it('replays the original accepted signup after reload only when its status is absent', async () => {
  sessionStorage.clear();
  const original = {
    operationId: '550e8400-e29b-41d4-a716-446655440000',
    revision: 'accepted-once',
    termsVersion: null,
    acceptedTerms: false,
    requestedImmediateStart: false,
    approvedSpecificClauses: false,
    language: 'en',
  };
  sessionStorage.setItem(storageKey('paid-signup'), JSON.stringify(original));
  vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
  vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
  vi.mocked(appConnectionService.list).mockResolvedValue([]);
  vi.mocked(usageService.get).mockResolvedValue(usageWith());
  vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
    ...SUBSCRIBED,
    subscription: null,
    freeAccess: { startsAt: '2028-01-31T12:00:00Z', endsAt: '2028-03-31T12:00:00Z', months: 2 },
  });
  vi.mocked(billingService.fetchPaidSignup)
    .mockReset()
    .mockRejectedValue(apiError(404, 'Not found'));
  vi.mocked(billingService.createPaidSignup).mockReset().mockResolvedValue({
    operationId: original.operationId,
    status: 'pending',
    detail: null,
    url: 'https://checkout.test/existing-setup',
    sessionId: 'cs_existing',
    firstPaymentAt: '2028-03-31T12:00:00Z',
    planKey: 'pumpkit_pro_monthly',
  });
  vi.mocked(redirectTo).mockClear();
  renderSettings();
  const plan = await card('Plan');
  const resume = await plan.findByRole('button', { name: 'Continue checkout' });
  expect(billingService.createPaidSignup).toHaveBeenCalledTimes(1);
  expect(billingService.createPaidSignup).toHaveBeenCalledWith(original);
  expect(redirectTo).not.toHaveBeenCalled();
  fireEvent.click(resume);
  expect(redirectTo).toHaveBeenCalledWith('https://checkout.test/existing-setup');
  expect(sessionStorage.getItem(storageKey('paid-signup'))).toContain(original.operationId);
});

it.each(['http-conflict', 'completed-with-detail', 'unknown-conflict'])(
  'handles signup cancellation %s without false success',
  async (answer) => {
    sessionStorage.clear();
    sessionStorage.setItem(
      storageKey('paid-signup'),
      JSON.stringify({
        operationId: 'stale-signup',
        revision: 'stale-review',
        termsVersion: '2026-11-08',
        acceptedTerms: true,
        requestedImmediateStart: true,
        approvedSpecificClauses: true,
        language: 'en',
      }),
    );
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
    vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
    vi.mocked(appConnectionService.list).mockResolvedValue([]);
    vi.mocked(usageService.get).mockResolvedValue(usageWith());
    vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
    const free = { startsAt: '2028-01-31T12:00:00Z', endsAt: '2028-05-31T12:00:00Z', months: 4 };
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...SUBSCRIBED,
      subscription: null,
      pendingPaidSignupId: 'stale-signup',
      freeAccess: free,
    });
    vi.mocked(billingService.fetchPaidSignup).mockReset().mockResolvedValue({
      operationId: 'stale-signup',
      status: 'pending',
      detail: null,
      url: null,
      sessionId: 'cs_old',
      firstPaymentAt: '2028-03-31T12:00:00Z',
      planKey: 'pumpkit_pro_monthly',
    });
    const detail =
      'Cancellation could not be confirmed from this signup. Review your current plan in Settings, then use Cancel renewal or Manage subscription.';
    vi.mocked(billingService.cancelPaidSignup)
      .mockReset()
      .mockImplementation(async () => {
        if (answer === 'unknown-conflict')
          throw apiError(409, 'Your paid signup customer is being confirmed.');
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
          ...SUBSCRIBED,
          subscription: {
            status: 'trialing',
            planKey: 'pumpkit_pro_monthly',
            currentPeriodEnd: free.endsAt,
            cancelAt: null,
          },
          couponDeferral: true,
          freeAccess: free,
        });
        if (answer === 'http-conflict')
          throw apiError(409, detail, { code: 'PAID_SIGNUP_CANCEL_CONFLICT' });
        return {
          operationId: 'stale-signup',
          status: 'completed',
          detail,
          url: null,
          sessionId: 'cs_old',
          firstPaymentAt: '2028-03-31T12:00:00Z',
          planKey: 'pumpkit_pro_monthly',
        };
      });
    renderSettings();
    const plan = await card('Plan');
    await waitFor(() => expect(plan.getByRole('button', { name: 'Cancel signup' })).toBeEnabled());
    fireEvent.click(plan.getByRole('button', { name: 'Cancel signup' }));
    if (answer === 'unknown-conflict') {
      expect(
        await plan.findByText(/Check signup to retrieve its result safely/),
      ).toBeInTheDocument();
      expect(plan.getByRole('button', { name: 'Check signup' })).toBeEnabled();
      expect(plan.getByRole('button', { name: 'Cancel signup' })).toBeEnabled();
      expect(plan.queryByText(/Subscription arranged/)).not.toBeInTheDocument();
      expect(sessionStorage.getItem(storageKey('paid-signup'))).toContain('stale-signup');
      return;
    }
    expect(await plan.findByText(detail)).toBeInTheDocument();
    expect(plan.queryByText(/Subscription arranged/)).not.toBeInTheDocument();
    expect(await plan.findByRole('button', { name: 'Cancel renewal' })).toBeEnabled();
    expect(plan.getByText('Next payment: May 31, 2028 UTC')).toBeInTheDocument();
    expect(plan.queryByRole('button', { name: 'Cancel signup' })).not.toBeInTheDocument();
    expect(sessionStorage.getItem(storageKey('paid-signup'))).toBeNull();
  },
);

describe('future billing frequency', () => {
  const paymentAt = '2028-03-31T12:00:00Z';
  const free = {
    startsAt: '2028-02-29T12:00:00Z',
    endsAt: paymentAt,
    months: 1,
    queuedStartsAt: '2028-02-29T12:00:00Z',
  };
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);
    vi.mocked(userService.fetchProfile).mockResolvedValue(ADA);
    vi.mocked(appConnectionService.list).mockResolvedValue([]);
    vi.mocked(usageService.get).mockResolvedValue(usageWith());
    vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, couponsEnabled: true });
    vi.mocked(billingService.previewPlanChange).mockReset();
    vi.mocked(billingService.createPlanChange).mockReset();
    vi.mocked(billingService.fetchPlanChange).mockReset();
  });

  it.each(['month', 'year'])(
    'reviews and confirms a future %s plan without losing coverage',
    async (interval) => {
      const target = CATALOG.plans.find((p) => p.interval === interval)!;
      const original = CATALOG.plans.find((p) => p.interval !== interval)!;
      const me = {
        ...holding('trialing', true),
        couponDeferral: true,
        mayChangePlan: true,
        subscription: {
          ...holding('trialing', true).subscription!,
          planKey: original.key,
          paidThrough: free.startsAt,
          currentPeriodEnd: paymentAt,
        },
        freeAccess: free,
      };
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(me);
      const future = {
        planKey: target.key,
        productName: target.productName,
        amount: target.amount,
        currency: target.currency,
        interval,
        intervalCount: 1,
        firstPaymentAt: paymentAt,
      };
      vi.mocked(billingService.previewPlanChange).mockResolvedValue({
        ...future,
        revision: 'accepted-frequency-offer',
      });
      vi.mocked(billingService.createPlanChange).mockImplementation(async (request) => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
          ...me,
          futurePlan: future,
          subscription: { ...me.subscription, planKey: target.key },
        });
        return { ...future, operationId: request.operationId, status: 'completed', detail: null };
      });
      renderSettings();
      const plan = await card('Plan');
      fireEvent.click(await plan.findByRole('button', { name: 'Change billing frequency' }));
      fireEvent.click(
        plan.getByRole('button', {
          name: interval === 'month' ? 'Review monthly plan' : 'Review yearly plan',
        }),
      );
      const review = await plan.findByRole('region', { name: 'Review billing frequency' });
      expect(review).toHaveFocus();
      expect(review).toHaveTextContent('March 31, 2028');
      expect(review).toHaveTextContent('12:00:00 UTC');
      expect(review).toHaveTextContent(interval === 'month' ? '€9.00 / month' : '€90.00 / year');
      expect(review).toHaveTextContent('No immediate payment');
      expect(billingService.createPlanChange).not.toHaveBeenCalled();
      fireEvent.click(within(review).getByRole('button', { name: 'Confirm change' }));
      const success = await plan.findByText(
        'Billing frequency changed. Your paid and free access stay unchanged.',
      );
      expect(success.closest('[role="status"]')).toHaveFocus();
      expect(plan.getByText(/Your future plan:/)).toHaveTextContent(target.productName);
      expect(plan.getByText(/Future payment:/)).toHaveTextContent('March 31, 2028');
      expect(plan.getByText(/Paid access through/)).toHaveTextContent('February 29, 2028');
      expect(plan.getByText(/Queued free access:/)).toHaveTextContent('March 31, 2028');
      expect(plan.getByRole('button', { name: 'Cancel renewal' })).toBeEnabled();
      expect(billingService.createPlanChange).toHaveBeenCalledWith(
        expect.objectContaining({ revision: 'accepted-frequency-offer' }),
      );
    },
  );

  it('recovers an uncertain change with coupons off and blocks conflicting billing until confirmed', async () => {
    const future = {
      planKey: 'pumpkit_pro_yearly',
      productName: 'Pro yearly',
      amount: 9000,
      currency: 'eur',
      interval: 'year',
      intervalCount: 1,
      firstPaymentAt: paymentAt,
    };
    vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
    const me = {
      ...holding('trialing', true),
      couponDeferral: true,
      pendingPlanChangeId: 'account-plan-change',
      subscription: {
        ...holding('trialing', true).subscription!,
        paidThrough: free.startsAt,
        currentPeriodEnd: paymentAt,
      },
      freeAccess: free,
    };
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(me);
    vi.mocked(billingService.fetchPlanChange).mockResolvedValueOnce({
      ...future,
      operationId: 'account-plan-change',
      status: 'pending',
      detail: 'Confirming the billing change.',
    });
    renderSettings();
    const plan = await card('Plan');
    expect(await plan.findByText('Confirming the billing change.')).toBeInTheDocument();
    expect(plan.getByRole('button', { name: 'Cancel renewal' })).toBeDisabled();
    expect(
      plan.queryByRole('button', { name: 'Change billing frequency' }),
    ).not.toBeInTheDocument();
    expect(plan.queryByRole('button', { name: 'Redeem coupon' })).not.toBeInTheDocument();
    vi.mocked(billingService.fetchPlanChange).mockImplementation(async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
        ...me,
        pendingPlanChangeId: null,
        futurePlan: future,
      });
      return { ...future, operationId: 'account-plan-change', status: 'completed', detail: null };
    });
    fireEvent.click(plan.getByRole('button', { name: 'Check billing change' }));
    expect(await plan.findByText(/Billing frequency changed/)).toBeInTheDocument();
    await waitFor(() => expect(plan.getByRole('button', { name: 'Cancel renewal' })).toBeEnabled());
    expect(plan.getByText(/Your future plan:/)).toHaveTextContent('Pro yearly');
    expect(billingService.createPlanChange).not.toHaveBeenCalled();
  });

  it('retains an interrupted confirmation for lookup after reload, without starting another change', async () => {
    const me = {
      ...holding('trialing', true),
      couponDeferral: true,
      mayChangePlan: true,
      subscription: { ...holding('trialing', true).subscription!, currentPeriodEnd: paymentAt },
      freeAccess: free,
    };
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(me);
    const future = {
      planKey: 'pumpkit_pro_yearly',
      productName: 'Pro yearly',
      amount: 9000,
      currency: 'eur',
      interval: 'year',
      intervalCount: 1,
      firstPaymentAt: paymentAt,
    };
    vi.mocked(billingService.previewPlanChange).mockResolvedValue({
      ...future,
      revision: 'interrupted-offer',
    });
    vi.mocked(billingService.createPlanChange).mockRejectedValue(apiError(502, 'Unavailable'));
    const view = renderSettings();
    let plan = await card('Plan');
    fireEvent.click(await plan.findByRole('button', { name: 'Change billing frequency' }));
    fireEvent.click(plan.getByRole('button', { name: 'Review yearly plan' }));
    fireEvent.click(await plan.findByRole('button', { name: 'Confirm change' }));
    expect(await plan.findByRole('alert')).toHaveTextContent('not confirmed yet');
    expect(plan.getByRole('button', { name: 'Cancel renewal' })).toBeDisabled();
    const saved = JSON.parse(sessionStorage.getItem(storageKey('plan-change'))!);
    expect(saved.revision).toBe('interrupted-offer');
    expect(billingService.createPlanChange).toHaveBeenCalledTimes(1);
    view.unmount();
    vi.mocked(billingService.fetchPlanChange).mockResolvedValue({
      ...future,
      operationId: saved.operationId,
      status: 'completed',
      detail: null,
    });
    renderSettings();
    plan = await card('Plan');
    expect(await plan.findByText(/Billing frequency changed/)).toBeInTheDocument();
    expect(billingService.fetchPlanChange).toHaveBeenCalledWith(saved.operationId);
    expect(billingService.createPlanChange).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(storageKey('plan-change'))).toBeNull();
  });

  it('requires a fresh review after a stale offer and keeps the current payment date visible', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...holding('trialing', true),
      couponDeferral: true,
      mayChangePlan: true,
      subscription: { ...holding('trialing', true).subscription!, currentPeriodEnd: paymentAt },
      freeAccess: free,
    });
    const future = {
      planKey: 'pumpkit_pro_yearly',
      productName: 'Pro yearly',
      amount: 9000,
      currency: 'eur',
      interval: 'year',
      intervalCount: 1,
      firstPaymentAt: paymentAt,
    };
    vi.mocked(billingService.previewPlanChange).mockResolvedValue({
      ...future,
      revision: 'stale-offer',
    });
    vi.mocked(billingService.createPlanChange).mockRejectedValue(
      apiError(409, 'The billing offer changed. Review it again.'),
    );
    renderSettings();
    const plan = await card('Plan');
    fireEvent.click(await plan.findByRole('button', { name: 'Change billing frequency' }));
    fireEvent.click(plan.getByRole('button', { name: 'Review yearly plan' }));
    fireEvent.click(await plan.findByRole('button', { name: 'Confirm change' }));
    expect(await plan.findByRole('alert')).toHaveTextContent('Review it again');
    expect(plan.queryByRole('button', { name: 'Confirm change' })).not.toBeInTheDocument();
    expect(plan.getByText(/Next payment:/)).toHaveTextContent('March 31, 2028');
    expect(sessionStorage.getItem(storageKey('plan-change'))).toBeNull();
    expect(plan.getByRole('button', { name: 'Review yearly plan' })).toBeEnabled();
  });

  it('keeps ordinary cancellation and payment-method management available on an enabled instance', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('active', true));
    vi.mocked(billingService.openBillingPortal).mockResolvedValue(
      'https://portal.stripe.test/safe',
    );
    vi.mocked(redirectTo).mockClear();
    renderSettings();
    const plan = await card('Plan');
    expect(await plan.findByRole('button', { name: 'Cancel renewal' })).toBeEnabled();
    fireEvent.click(plan.getByRole('button', { name: 'Manage billing' }));
    await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://portal.stripe.test/safe'));
    expect(
      plan.queryByRole('button', { name: 'Change billing frequency' }),
    ).not.toBeInTheDocument();
  });

  it('offers no new frequency or ordinary cancellation controls with coupons disabled', async () => {
    vi.mocked(billingService.fetchPlans).mockResolvedValue(CATALOG);
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
      ...holding('active', true),
      mayChangePlan: true,
    });
    renderSettings();
    const plan = await card('Plan');
    expect(await plan.findByRole('button', { name: 'Manage subscription' })).toBeEnabled();
    expect(plan.queryByRole('button', { name: 'Cancel renewal' })).not.toBeInTheDocument();
    expect(
      plan.queryByRole('button', { name: 'Change billing frequency' }),
    ).not.toBeInTheDocument();
    expect(billingService.previewPlanChange).not.toHaveBeenCalled();
  });
});
