import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';

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
    startTopUpCheckout: vi.fn(),
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
    acceptPhoto: vi.fn(),
    declinePhoto: vi.fn(),
  },
}));
vi.mock('@/services/apiKeyService', () => ({
  apiKeyService: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
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
vi.mock('@/services/usageService', () => ({ usageService: { get: vi.fn() } }));
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
import { usageService } from '@/services/usageService';
import { userService, type UserProfile } from '@/services/userService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import { AppLayout } from './AppLayout';
import { BillingSuccessRedirect } from './BillingRedirect';
import { signedInRoutes } from './signedInRoutes';
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
  needsReconnect: false,
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
  termsVersion: '2026-10-11',
  allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
  trial: { days: 7, generations: 125, xPosts: 25, linkXPosts: 2 },
  topUp: null,
};

const TOP_UP = { amount: 1000, currency: 'eur', generations: 250, xPosts: 50, linkXPosts: 5 };

const WITH_TRIAL: BillingMe = { ...NOT_SUBSCRIBED, trialDays: 7 };

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
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(xConnectionService.startAuthorization).mockReset();
    vi.mocked(xConnectionService.disconnect).mockReset();
    vi.mocked(xConnectionService.acceptPhoto).mockReset();
    vi.mocked(xConnectionService.declinePhoto).mockReset().mockResolvedValue();
    vi.mocked(apiKeyService.list).mockReset().mockResolvedValue([]);
    vi.mocked(usageService.get).mockReset().mockResolvedValue(usageWith());
    vi.mocked(redirectTo).mockReset();
    vi.mocked(fireSuccessConfetti).mockReset();
    vi.mocked(track).mockClear();
  });

  it('shows Profile, X account, Plan, Usage, API keys and Appearance to a Subscribed User', async () => {
    renderSettings();

    await card('Usage');
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Profile',
      'X account',
      'Plan',
      'Usage',
      'API keys',
      'Appearance',
    ]);
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('puts Choose a plan first for a User who is not Subscribed', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
    renderSettings();

    await card('Choose a plan');
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Choose a plan',
      'Profile',
      'X account',
      'Plan',
      'API keys',
      'Appearance',
    ]);
    expect((await card('Plan')).getByText('No subscription')).toBeInTheDocument();
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

    it('lets a User who is not Subscribed still see and disconnect their X connection', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      renderSettings();

      const x = await card('X account');
      expect(await x.findByText('@ada')).toBeInTheDocument();
      expect(x.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();
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

    it('sends a User who is not Subscribed to Choose a plan instead of connecting', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderSettings();

      const x = await card('X account');
      expect(await x.findByText('Connecting X needs a subscription.')).toBeInTheDocument();
      expect(x.queryByRole('button', { name: 'Connect X' })).not.toBeInTheDocument();
      expect(x.getByRole('link', { name: 'Subscribe' })).toHaveAttribute(
        'href',
        '/settings#choose-a-plan',
      );
    });
  });

  describe('Plan', () => {
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
        expect(screen.queryByRole('region', { name: 'Choose a plan' })).not.toBeInTheDocument();
      },
    );

    it('says when a Subscription set to cancel ends', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(holding('active', true, true));
      renderSettings();

      expect(
        await (await card('Plan')).findByText(`Ends on ${PERIOD_END_LABEL}`),
      ).toBeInTheDocument();
    });

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
      expect(usageCard.getByText('Resets on 14 November')).toBeInTheDocument();
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

    it('greets a bought top-up and loads usage once more after a short wait', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      onTestFinished(() => {
        vi.useRealTimers();
      });
      renderSettings({ state: { checkoutStatus: 'top_up_bought' } });

      await card('Usage');
      await waitFor(() => expect(usageService.get).toHaveBeenCalledTimes(1));
      expect(track).toHaveBeenCalledWith('top_up_bought');
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(usageService.get).toHaveBeenCalledTimes(2);
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

  describe('Choose a plan', () => {
    beforeEach(() => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(WITH_TRIAL);
    });

    it('offers each Plan with its price and the free trial', async () => {
      renderSettings();

      const choose = await card('Choose a plan');
      expect(await choose.findByText('Pro')).toBeInTheDocument();
      expect(choose.getByText('Pro yearly')).toBeInTheDocument();
      expect(choose.getByText(/€9\.00 \/ month/)).toBeInTheDocument();
      expect(
        choose.getByText('7-day free trial: 125 generations and 25 X posts, up to 2 with a link.'),
      ).toBeInTheDocument();
    });

    it("lists what the Plan allows, with the Instance's caps", async () => {
      renderSettings();

      const offer = within(
        await (await card('Choose a plan')).findByRole('list', { name: 'Included' }),
      );
      expect(offer.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        '500 post generations a month.',
        'Publish 100 X posts a month, up to 10 of them with a link.',
        'Write in the voice of your favorite X creators.',
        '7-day free trial: 125 generations and 25 X posts, up to 2 with a link.',
      ]);
    });

    it.each([
      ['About generations', 'Every prompt to generate or refine a post counts as one generation.'],
      [
        'About X posts',
        'Scheduled posts and posts you post now both count. For threads, each post in the thread counts.',
      ],
    ])('explains what counts behind %s', async (button, text) => {
      renderSettings();
      const choose = await card('Choose a plan');

      fireEvent.click(await choose.findByRole('button', { name: button }));

      expect(await screen.findByRole('dialog', { name: button })).toHaveTextContent(text);
    });

    it('drops the line of a cap the Instance leaves empty', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({
        ...CATALOG,
        allowance: { generations: null, xPosts: 100, linkXPosts: null },
        trial: { days: 7, generations: null, xPosts: 25, linkXPosts: null },
      });
      renderSettings();

      const choose = await card('Choose a plan');
      const offer = within(await choose.findByRole('list', { name: 'Included' }));
      expect(offer.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        'Publish 100 X posts a month.',
        'Write in the voice of your favorite X creators.',
        '7-day free trial: 25 X posts.',
      ]);
      expect(choose.queryByRole('button', { name: 'About generations' })).not.toBeInTheDocument();
    });

    it('offers the Plans to a User whose Subscription is still incomplete', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue({
        ...holding('incomplete', false),
        maySubscribe: true,
      });
      renderSettings();

      const choose = await card('Choose a plan');
      expect(await choose.findByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
      expect(
        (await card('Plan')).queryByRole('button', { name: /manage/i }),
      ).not.toBeInTheDocument();
    });

    it('keeps "Start free trial" disabled until the three boxes are ticked, then starts checkout', async () => {
      renderSettings();

      const choose = await card('Choose a plan');
      const start = await choose.findByRole('button', { name: 'Start free trial of Pro yearly' });
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

      const choose = await card('Choose a plan');
      await choose.findByRole('button', { name: 'Start free trial of Pro' });
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

      const choose = await card('Choose a plan');
      expect(await choose.findByRole('button', { name: 'Subscribe to Pro' })).toBeInTheDocument();
      expect(choose.queryByText(/free trial/)).not.toBeInTheDocument();
      expect(choose.getByText('500 post generations a month.')).toBeInTheDocument();
    });

    it('starts checkout with only the Plan key where the Instance has no Terms', async () => {
      vi.mocked(billingService.fetchPlans).mockResolvedValue({ ...CATALOG, termsVersion: null });
      renderSettings();

      const choose = await card('Choose a plan');
      const start = await choose.findByRole('button', { name: 'Start free trial of Pro' });
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

      const choose = await card('Choose a plan');
      const start = await choose.findByRole('button', { name: 'Start free trial of Pro' });
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

      const choose = await card('Choose a plan');
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
    it('shows neither Choose a plan nor Plan, and asks nothing about billing', async () => {
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
      expect(usageService.get).not.toHaveBeenCalled();
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
