import { fireEvent, screen, waitFor, within } from '@testing-library/react';
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
  xConnectionService: { get: vi.fn().mockResolvedValue(null) },
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

import { track } from '@/lib/analytics';
import {
  authorDirectoryService,
  type AuthorDirectoryEntry,
} from '@/services/authorDirectoryService';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { onboardingService } from '@/services/onboardingService';
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
});
