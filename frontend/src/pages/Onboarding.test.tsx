import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
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
    fetchPlans: vi.fn().mockResolvedValue({ plans: [], termsVersion: '2026-10-11' }),
  },
}));
vi.mock('@/services/inspirationAuthorService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/inspirationAuthorService')>()),
  inspirationAuthorService: {
    list: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
    refresh: vi.fn(),
  },
}));
vi.mock('@/services/authorDirectoryService', () => ({
  authorDirectoryService: { list: vi.fn() },
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
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn(), finish: vi.fn() },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { SELLS_PLANS } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { DEFAULT_INSTANCE } from '@/lib/instance';
import { redirectTo } from '@/lib/navigation';
import {
  authorDirectoryService,
  type AuthorDirectoryEntry,
} from '@/services/authorDirectoryService';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { onboardingService } from '@/services/onboardingService';
import { xConnectionService } from '@/services/xConnectionService';
import { LEVELSIO, SUBSCRIBED, apiError, currentPath, renderSignedIn } from './testing/signedInApp';

function entry(handle: string, name: string, personaCount = 0): AuthorDirectoryEntry {
  return { handle, name, photoUrl: null, personaCount };
}

// Real seed names from `backend/alembic/data/author_seeds.json`.
const DIRECTORY: AuthorDirectoryEntry[] = [
  entry('levelsio', 'Pieter Levels', 3),
  entry('paulg', 'Paul Graham', 5),
  entry('naval', 'Naval Ravikant', 5),
];

const PIETER = { ...LEVELSIO, name: 'Pieter Levels' };

function renderOnboarding(path = '/onboarding') {
  return renderSignedIn(path, { nextStep: 'persona' });
}

async function step() {
  return within(
    await screen.findByRole('region', { name: 'Choose up to three authors to write like' }),
  );
}

async function pick(query: string) {
  const field = await (await step()).findByRole('combobox', { name: 'Find an author' });
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: query } });
  fireEvent.keyDown(field, { key: 'Enter' });
}

async function xStep() {
  return within(await screen.findByRole('region', { name: 'Connect your X account' }));
}

function continueButton() {
  return screen.getByRole('button', { name: 'Continue' });
}

describe('Onboarding', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([]);
    vi.mocked(inspirationAuthorService.add).mockReset();
    vi.mocked(inspirationAuthorService.remove).mockReset();
    vi.mocked(authorDirectoryService.list).mockReset().mockResolvedValue(DIRECTORY);
    vi.mocked(onboardingService.fetchNextStep).mockReset().mockResolvedValue('persona');
    vi.mocked(onboardingService.finish).mockReset().mockResolvedValue(undefined);
    vi.mocked(xConnectionService.startAuthorization).mockReset();
    vi.mocked(redirectTo).mockClear();
    vi.mocked(track).mockClear();
  });

  describe('the routing', () => {
    it.each(['/new', '/persona', '/settings', '/posts/post_01', '/subscribe'])(
      'sends a User at the Persona step from %s to /onboarding',
      async (path) => {
        renderOnboarding(path);

        await step();
        expect(currentPath()).toBe('/onboarding');
      },
    );

    it('sends a User who finished Onboarding from /onboarding to New post', async () => {
      renderSignedIn('/onboarding', { nextStep: null });

      await waitFor(() => expect(currentPath()).toBe('/new'));
    });

    it.each(['/new', '/settings', '/persona'])(
      'sends a User at the X step from %s to /onboarding',
      async (path) => {
        renderSignedIn(path, { nextStep: 'x_connection' });

        await xStep();
        expect(currentPath()).toBe('/onboarding');
      },
    );

    it('sends a User who is not Subscribed from /onboarding to the Paywall', async () => {
      renderSignedIn('/onboarding', { nextStep: 'paywall' });

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });
  });

  describe('the Persona step', () => {
    it('renders in the onboarding shell, with Persona as the current step', async () => {
      renderOnboarding();

      await step();
      const steps = screen.getByRole('navigation', { name: 'Steps' });
      expect(steps.querySelector('[aria-current="step"]')).toHaveTextContent('Persona');
      expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
    });

    it('records that the Persona step was viewed, once', async () => {
      renderOnboarding();

      await step();
      expect(vi.mocked(track).mock.calls).toEqual([
        ['onboarding_step_viewed', { step: 'persona' }],
      ]);
    });

    it('resumes with the authors the User already picked', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([PIETER]);
      renderOnboarding();

      const panel = await step();
      expect(await panel.findByRole('list', { name: '1 of 3 places taken' })).toBeInTheDocument();
      expect(panel.getByText('Pieter Levels')).toBeInTheDocument();
      expect(continueButton()).toBeEnabled();
    });

    it('keeps Continue disabled until a slot is filled and done fetching', async () => {
      let added: (author: typeof PIETER) => void = () => {};
      vi.mocked(inspirationAuthorService.add).mockReturnValue(
        new Promise((resolve) => (added = resolve)),
      );
      renderOnboarding();

      const panel = await step();
      expect(continueButton()).toBeDisabled();

      await pick('levels');
      expect(await panel.findByText("Reading @levelsio's posts…")).toBeInTheDocument();
      expect(continueButton()).toBeDisabled();

      added(PIETER);
      await waitFor(() => expect(continueButton()).toBeEnabled());
      expect(panel.getByText('Pieter Levels')).toBeInTheDocument();
    });

    it('says more authors give a steadier style', async () => {
      renderOnboarding();

      expect((await step()).getByText('More authors give a steadier style.')).toBeInTheDocument();
    });

    it('records the finish and lands on New post when Continue is pressed', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([PIETER]);
      renderOnboarding();
      await step();
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);

      fireEvent.click(continueButton());

      await waitFor(() => expect(currentPath()).toBe('/new'));
      expect(onboardingService.finish).toHaveBeenCalledTimes(1);
      expect(track).toHaveBeenCalledWith('onboarding_finished');
    });

    it('shows why the finish was refused and stays on the step', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([PIETER]);
      vi.mocked(onboardingService.finish).mockRejectedValue(
        apiError(409, 'Pick at least one inspiration author to continue.'),
      );
      renderOnboarding();
      await step();

      fireEvent.click(continueButton());

      expect(
        await screen.findByText('Pick at least one inspiration author to continue.'),
      ).toBeInTheDocument();
      expect(currentPath()).toBe('/onboarding');
      expect(track).not.toHaveBeenCalledWith('onboarding_finished');
    });

    it('sends a User whose Subscription ended to the Paywall when Continue is refused for it', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([PIETER]);
      vi.mocked(onboardingService.finish).mockRejectedValue(
        apiError(403, 'This needs a subscription. Subscribe to continue.'),
      );
      renderOnboarding();
      await step();
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('paywall');

      fireEvent.click(continueButton());

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });
  });

  describe('the X step', () => {
    function renderXStep(state?: unknown) {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('x_connection');
      return renderSignedIn('/onboarding', { nextStep: 'x_connection', state });
    }

    it('offers one Connect X button and says the User comes back from X', async () => {
      renderXStep();

      const area = await xStep();
      expect(area.getByText('Pumpkit publishes your posts from this account.')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Connect X' })).toBeEnabled();
      expect(
        area.getByText("You'll approve access on X, then come back here."),
      ).toBeInTheDocument();
      expect(vi.mocked(track).mock.calls).toEqual([
        ['onboarding_step_viewed', { step: 'x_connection' }],
      ]);
    });

    it('shows Connect X as the current step, after the Plan', async () => {
      renderXStep();

      await xStep();
      const steps = within(screen.getByRole('navigation', { name: 'Steps' }));
      const listed = within(steps.getByRole('list'));
      expect(listed.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        'Plan (done)',
        '2Connect X',
        '3Persona',
      ]);
      expect(listed.getByText('Connect X').closest('[aria-current="step"]')).not.toBeNull();
      expect(steps.getByText(/Step 2 of 3/)).toBeInTheDocument();
    });

    it('starts at Connect X on an Instance that sells no Plans', async () => {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('x_connection');
      renderSignedIn('/onboarding', {
        nextStep: 'x_connection',
        instance: { ...DEFAULT_INSTANCE, x_connection: true },
      });

      await xStep();
      const listed = within(screen.getByRole('navigation', { name: 'Steps' }));
      expect(listed.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        '1Connect X',
        '2Persona',
      ]);
    });

    it('leaves for X, saying so on the disabled button', async () => {
      vi.mocked(xConnectionService.startAuthorization).mockResolvedValue('https://x.com/i/oauth2');
      renderXStep();
      const area = await xStep();

      fireEvent.click(area.getByRole('button', { name: 'Connect X' }));

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2'));
      expect(area.getByRole('button', { name: 'Opening X…' })).toBeDisabled();
    });

    it('shows why X could not be opened, with Try again', async () => {
      vi.mocked(xConnectionService.startAuthorization).mockRejectedValue(
        apiError(503, 'X_CLIENT_ID and X_CLIENT_SECRET must be set in .env to connect X accounts.'),
      );
      renderXStep();
      const area = await xStep();

      fireEvent.click(area.getByRole('button', { name: 'Connect X' }));

      expect(
        await area.findByText(
          'X_CLIENT_ID and X_CLIENT_SECRET must be set in .env to connect X accounts.',
        ),
      ).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Try again' })).toBeEnabled();
    });

    it('shows the reason an authorization failed on the way back, with Try again', async () => {
      renderXStep({ xConnection: { outcome: 'failed', reason: 'X refused the code. Try again.' } });

      const area = await xStep();
      expect(area.getByRole('alert')).toHaveTextContent('X refused the code. Try again.');
      expect(area.getByRole('button', { name: 'Try again' })).toBeEnabled();
    });

    it('says plainly when the X account belongs to another Pumpkit account', async () => {
      renderXStep({ xConnection: { outcome: 'taken' } });

      const area = await xStep();
      expect(area.getByRole('alert')).toHaveTextContent(
        'That X account is connected to another Pumpkit account.',
      );
      expect(area.getByRole('button', { name: 'Try again' })).toBeEnabled();
    });

    it('moves on when the User comes back having connected X in another tab', async () => {
      renderXStep();
      await xStep();
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('persona');

      act(() => {
        window.dispatchEvent(new Event('focus'));
      });

      expect(await step()).toBeDefined();
    });

    it('shows the connected account for a moment, then the Persona step', async () => {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('persona');
      renderSignedIn('/onboarding', {
        nextStep: 'persona',
        state: {
          xConnection: { outcome: 'connected', handle: 'ada', photoUrl: null },
        },
      });

      const connected = await screen.findByRole('status', { name: 'X connected' });
      expect(connected).toHaveTextContent('@ada');
      expect(
        screen.queryByRole('region', { name: 'Choose up to three authors to write like' }),
      ).not.toBeInTheDocument();

      expect(
        await screen.findByRole(
          'region',
          { name: 'Choose up to three authors to write like' },
          { timeout: 3000 },
        ),
      ).toBeInTheDocument();
      expect(screen.queryByRole('status', { name: 'X connected' })).not.toBeInTheDocument();
    });
  });

  describe('an Instance without X', () => {
    const NO_X = { ...SELLS_PLANS, x_connection: false };

    it('leaves the X step out of the indicator and renumbers it', async () => {
      renderSignedIn('/onboarding', { nextStep: 'persona', instance: NO_X });

      await step();
      const steps = within(screen.getByRole('navigation', { name: 'Steps' }));
      const listed = within(steps.getByRole('list'));
      expect(listed.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        'Plan (done)',
        '2Persona',
      ]);
      expect(steps.getByText(/Step 2 of 2/)).toBeInTheDocument();
      expect(screen.queryByText('Connect X')).not.toBeInTheDocument();
    });
  });
});
