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
vi.mock('@/services/positioningService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/positioningService')>()),
  positioningService: { get: vi.fn(), save: vi.fn(), draft: vi.fn() },
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
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import { onboardingService } from '@/services/onboardingService';
import { positioningService } from '@/services/positioningService';
import { xConnectionService } from '@/services/xConnectionService';
import { SUBSCRIBED, apiError, currentPath, renderSignedIn } from './testing/signedInApp';

const DRAFTED = "I'm a solo founder building a pricing tool. I post about pricing for founders.";
const EDITED = `${DRAFTED} I post to earn sign-ups.`;
const NOT_READ = "We couldn't read your X profile. Write it yourself, a few sentences is enough.";

function renderOnboarding(path = '/onboarding') {
  return renderSignedIn(path, { nextStep: 'persona' });
}

async function step() {
  return within(await screen.findByRole('region', { name: 'Who you are on X' }));
}

async function field() {
  return (await step()).findByRole('textbox', { name: 'Who you are on X' });
}

function continueButton() {
  return screen.getByRole('button', { name: 'Continue' });
}

/** Renders the step and waits for the draft to fill the textarea. */
async function drafted() {
  renderOnboarding();
  await waitFor(async () => expect(await field()).toHaveValue(DRAFTED));
}

describe('Onboarding', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(positioningService.get).mockReset().mockResolvedValue({ text: null, canDraft: true });
    vi.mocked(positioningService.draft)
      .mockReset()
      .mockResolvedValue({ text: DRAFTED, reason: null, canDraft: true });
    vi.mocked(positioningService.save)
      .mockReset()
      .mockImplementation(async (text) => ({ text }));
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

    it('sends a User who is not Subscribed from /onboarding to the Paywall, reading nothing from X', async () => {
      renderSignedIn('/onboarding', { nextStep: 'paywall' });

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
      expect(positioningService.draft).not.toHaveBeenCalled();
    });
  });

  describe('the Persona step', () => {
    it('renders in the onboarding shell, titled by the Positioning panel, with Persona as the current step', async () => {
      renderOnboarding();

      await step();
      expect(screen.getByRole('heading', { level: 1, name: 'Who you are on X' })).toBeVisible();
      const steps = screen.getByRole('navigation', { name: 'Steps' });
      expect(steps.querySelector('[aria-current="step"]')).toHaveTextContent('Persona');
      expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
    });

    it('records that the Persona step was viewed, once', async () => {
      await drafted();

      expect(vi.mocked(track).mock.calls).toEqual([
        ['onboarding_step_viewed', { step: 'persona' }],
      ]);
    });

    it('shows "Reading your X profile…" with the textarea and Continue disabled while the draft is on its way', async () => {
      vi.mocked(positioningService.draft).mockReturnValue(new Promise(() => {}));
      renderOnboarding();

      const textarea = await field();
      await waitFor(() =>
        expect(textarea).toHaveAttribute('placeholder', 'Reading your X profile…'),
      );
      expect(textarea).toBeDisabled();
      expect(textarea).toHaveValue('');
      expect(continueButton()).toBeDisabled();
      expect(positioningService.draft).toHaveBeenCalledTimes(1);
    });

    it('fills the textarea with the draft, which the User can edit, and saves nothing yet', async () => {
      await drafted();

      const textarea = await field();
      expect(textarea).toBeEnabled();
      fireEvent.change(textarea, { target: { value: EDITED } });
      expect(textarea).toHaveValue(EDITED);
      expect(continueButton()).toBeEnabled();
      expect(positioningService.draft).toHaveBeenCalledTimes(1);
      expect(positioningService.save).not.toHaveBeenCalled();
    });

    it('names the five things a Positioning covers under the textarea', async () => {
      await drafted();

      expect(await field()).toHaveAccessibleDescription(
        'Cover: who you are · what you post about · who you write for · what you post for · what you can point to',
      );
    });

    it('opens an empty textarea with the note when no draft can be made, and Continue waits for text', async () => {
      vi.mocked(positioningService.draft).mockResolvedValue({
        text: null,
        reason: NOT_READ,
        canDraft: true,
      });
      renderOnboarding();

      const region = await step();
      expect(await region.findByText(NOT_READ)).toBeInTheDocument();
      const textarea = await field();
      expect(textarea).toBeEnabled();
      expect(textarea).toHaveValue('');
      expect(textarea).toHaveAccessibleDescription(
        `${NOT_READ} Cover: who you are · what you post about · who you write for · what you post for · what you can point to`,
      );
      expect(continueButton()).toBeDisabled();

      fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
      expect(continueButton()).toBeEnabled();
    });

    it('opens an empty textarea with the note when the draft request fails', async () => {
      vi.mocked(positioningService.draft).mockRejectedValue(apiError(502, 'Bad gateway'));
      renderOnboarding();

      const textarea = await field();
      await waitFor(() => expect(textarea).toBeEnabled());
      expect(textarea).toHaveValue('');
      expect((await step()).getByRole('alert')).toBeInTheDocument();
    });

    it('asks for no draft when the User has used up the day’s drafts, and says when they can again', async () => {
      vi.mocked(positioningService.get).mockResolvedValue({ text: null, canDraft: false });
      renderOnboarding();

      const textarea = await field();
      await waitFor(() => expect(textarea).toBeEnabled());
      expect(textarea).toHaveValue('');
      expect((await step()).getByText('You can draft again tomorrow.')).toBeInTheDocument();
      expect(positioningService.draft).not.toHaveBeenCalled();
    });

    it('saves the edited Positioning, finishes Onboarding and lands on New post when Continue is pressed', async () => {
      await drafted();
      fireEvent.change(await field(), { target: { value: EDITED } });
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue(null);

      fireEvent.click(continueButton());

      await waitFor(() => expect(currentPath()).toBe('/new'));
      expect(positioningService.save).toHaveBeenCalledWith(EDITED);
      expect(onboardingService.finish).toHaveBeenCalledTimes(1);
      expect(vi.mocked(positioningService.save).mock.invocationCallOrder[0]).toBeLessThan(
        vi.mocked(onboardingService.finish).mock.invocationCallOrder[0],
      );
      expect(track).toHaveBeenCalledWith('onboarding_finished');
    });

    it('shows "Continuing…" and locks the textarea while Continue is on its way', async () => {
      vi.mocked(positioningService.save).mockReturnValue(new Promise(() => {}));
      await drafted();

      fireEvent.click(continueButton());

      const button = await screen.findByRole('button', { name: 'Continuing…' });
      expect(button).toBeDisabled();
      expect(await field()).toBeDisabled();
      expect(await field()).toHaveValue(DRAFTED);
      expect(
        (await step()).getByRole('button', { name: 'Draft again from my X profile' }),
      ).toBeDisabled();
    });

    it('keeps the text and says why under the textarea when the save fails, and stays on the step', async () => {
      vi.mocked(positioningService.save).mockRejectedValue(
        Object.assign(new Error('Network Error'), { isAxiosError: true }),
      );
      await drafted();

      fireEvent.click(continueButton());

      expect(
        await (await step()).findByText("Couldn't save your positioning. Try again."),
      ).toBeInTheDocument();
      expect(await field()).toHaveValue(DRAFTED);
      expect(onboardingService.finish).not.toHaveBeenCalled();
      expect(currentPath()).toBe('/onboarding');
      expect(continueButton()).toBeEnabled();
    });

    it('shows why the finish was refused and stays on the step', async () => {
      vi.mocked(onboardingService.finish).mockRejectedValue(
        apiError(409, 'Write your positioning to continue.'),
      );
      await drafted();

      fireEvent.click(continueButton());

      expect(
        await (await step()).findByText('Write your positioning to continue.'),
      ).toBeInTheDocument();
      expect(currentPath()).toBe('/onboarding');
      expect(continueButton()).toBeEnabled();
      expect(track).not.toHaveBeenCalledWith('onboarding_finished');
    });

    it('sends a User whose Subscription ended to the Paywall when Continue is refused for it', async () => {
      vi.mocked(positioningService.save).mockRejectedValue(
        apiError(403, 'This needs a subscription. Subscribe to continue.', {
          code: 'subscription_required',
        }),
      );
      await drafted();
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('paywall');

      fireEvent.click(continueButton());

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });
  });

  describe('the simplified step indicator', () => {
    const NO_X = { ...SELLS_PLANS, x_connection: false };

    it('contains only Plan then Persona', async () => {
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
