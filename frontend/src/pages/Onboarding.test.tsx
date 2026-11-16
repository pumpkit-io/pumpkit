import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
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
    fetchPlans: vi.fn().mockResolvedValue({ plans: [], termsVersion: '2026-10-11' }),
  },
}));
vi.mock('@/services/positioningService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/positioningService')>()),
  positioningService: { get: vi.fn(), save: vi.fn(), startDraft: vi.fn() },
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
import { positioningService, type PositioningDraft } from '@/services/positioningService';
import { xConnectionService } from '@/services/xConnectionService';
import { SUBSCRIBED, apiError, currentPath, renderSignedIn } from './testing/signedInApp';

const DRAFTED = "I'm a solo founder building a pricing tool. I post about pricing for founders.";
const EDITED = `${DRAFTED} I post to earn sign-ups.`;
const NOT_READ = "We couldn't read your X profile. Write it yourself.";
const NOT_DRAFTED = "We couldn't draft your positioning. Write it yourself.";
const READY: PositioningDraft = { state: 'ready', text: DRAFTED, reason: null };
const RUNNING: PositioningDraft = { state: 'running', text: null, reason: null };
const FAILED: PositioningDraft = { state: 'failed', text: null, reason: NOT_READ };

/** The draft the mocked server keeps for the User, which `get` reads. */
let kept: PositioningDraft | null;
/** What the mocked server's draft becomes when a start runs one. */
let started: PositioningDraft | null;
const ADVICE = 'Pumpkit plans every post around this. Two or three sentences are enough.';

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
  const rendered = renderOnboarding();
  await waitFor(async () => expect(await field()).toHaveValue(DRAFTED));
  return rendered;
}

describe('Onboarding', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    kept = null;
    started = READY;
    vi.mocked(positioningService.get)
      .mockReset()
      .mockImplementation(async () => ({ text: null, draft: kept }));
    vi.mocked(positioningService.startDraft)
      .mockReset()
      .mockImplementation(async () => {
        kept = started;
      });
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
      expect(positioningService.startDraft).not.toHaveBeenCalled();
    });
  });

  describe('the Persona step', () => {
    it('renders in the onboarding shell, titled by the Positioning panel, with Persona as the current step', async () => {
      renderOnboarding();

      await step();
      const heading = screen.getByRole('heading', { level: 1, name: 'Who you are on X' });
      expect(heading).toBeVisible();
      expect(within(heading).getByRole('img', { name: 'X' })).toBeInTheDocument();
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

    it('starts a draft once on opening, and fills the textarea with it, saving nothing yet', async () => {
      await drafted();

      const textarea = await field();
      expect(textarea).toBeEnabled();
      fireEvent.change(textarea, { target: { value: EDITED } });
      expect(textarea).toHaveValue(EDITED);
      expect(continueButton()).toBeEnabled();
      expect(positioningService.startDraft).toHaveBeenCalledTimes(1);
      expect(positioningService.save).not.toHaveBeenCalled();
    });

    it('fills the textarea with a draft already ready, starting none', async () => {
      kept = READY;

      await drafted();

      expect(positioningService.startDraft).not.toHaveBeenCalled();
    });

    it('shows "Reading your X profile…" with the textarea and Continue disabled while the Positioning loads', async () => {
      vi.mocked(positioningService.get).mockReturnValue(new Promise(() => {}));
      renderOnboarding();

      const textarea = await field();
      expect(textarea).toHaveAccessibleDescription(`Reading your X profile… ${ADVICE}`);
      expect(textarea).not.toHaveAttribute('placeholder');
      expect(textarea).toBeDisabled();
      expect(continueButton()).toBeDisabled();
    });

    describe('while the draft runs', () => {
      beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
      afterEach(() => vi.useRealTimers());

      it('shows "Reading your X profile…" with the textarea and Continue disabled', async () => {
        started = RUNNING;
        renderOnboarding();

        const textarea = await field();
        await waitFor(() =>
          expect(textarea).toHaveAccessibleDescription(`Reading your X profile… ${ADVICE}`),
        );
        // The words over the textarea, which describe it first, show X's logo.
        const [overlayId] = (textarea.getAttribute('aria-describedby') ?? '').split(' ');
        expect(document.getElementById(overlayId)?.querySelector('svg')).not.toBeNull();
        expect(textarea).not.toHaveAttribute('placeholder', 'Reading your X profile…');
        expect(textarea).toBeDisabled();
        expect(textarea).toHaveValue('');
        expect(continueButton()).toBeDisabled();
        expect(positioningService.startDraft).toHaveBeenCalledTimes(1);
      });

      it('reads the draft every 2 seconds and fills the textarea once it is ready', async () => {
        kept = RUNNING;
        renderOnboarding();
        const textarea = await field();
        await waitFor(() => expect(positioningService.get).toHaveBeenCalledTimes(1));

        await act(() => vi.advanceTimersByTimeAsync(2000));
        expect(positioningService.get).toHaveBeenCalledTimes(2);
        expect(textarea).toBeDisabled();

        kept = READY;
        await act(() => vi.advanceTimersByTimeAsync(2000));

        await waitFor(() => expect(textarea).toHaveValue(DRAFTED));
        expect(textarea).toBeEnabled();
        expect(positioningService.startDraft).not.toHaveBeenCalled();
      });

      it('tells a screen reader when the draft starts and when it fills the textarea', async () => {
        kept = RUNNING;
        renderOnboarding();
        await field();

        const status = (await step()).getByRole('status');
        await waitFor(() => expect(status).toHaveTextContent('Reading your X profile…'));

        kept = READY;
        await act(() => vi.advanceTimersByTimeAsync(2000));

        await waitFor(() => expect(status).toHaveTextContent('Your draft is ready to edit.'));
      });
    });

    it.each([
      ['no draft could be made', null, FAILED, NOT_READ],
      [
        'the draft from sign-in failed and so does the one the step starts',
        FAILED,
        FAILED,
        NOT_READ,
      ],
      // An Instance that can't draft, or a User with no draft request left today, starts none.
      ['the start runs no draft', FAILED, undefined, NOT_READ],
    ])(
      'opens an empty textarea with the reason in muted text when %s, and Continue waits for text',
      async (_case, before, after, reason) => {
        kept = before;
        started = after === undefined ? before : after;
        renderOnboarding();

        const textarea = await field();
        await waitFor(() => expect(textarea).toBeEnabled());
        expect(textarea).toHaveValue('');
        expect(textarea).toHaveAccessibleDescription(`${reason} ${ADVICE}`);
        expect((await step()).getByRole('status')).toHaveTextContent(reason);
        expect((await step()).queryByRole('alert')).not.toBeInTheDocument();
        expect(positioningService.startDraft).toHaveBeenCalledTimes(1);
        expect(continueButton()).toBeDisabled();

        fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
        expect(continueButton()).toBeEnabled();
      },
    );

    it('starts a draft again when the one from sign-in failed, and fills it', async () => {
      kept = FAILED;

      await drafted();

      expect(positioningService.startDraft).toHaveBeenCalledTimes(1);
    });

    it.each([
      ['the server fails', apiError(500, 'Something went wrong.')],
      ['the network is down', Object.assign(new Error('Network Error'), { isAxiosError: true })],
    ])(
      'opens an empty textarea with the reason when starting the draft fails: %s',
      async (_case, failure) => {
        vi.mocked(positioningService.startDraft).mockRejectedValue(failure);
        renderOnboarding();

        const textarea = await field();
        await waitFor(() => expect(textarea).toBeEnabled());
        expect(textarea).toHaveValue('');
        expect((await step()).getByRole('status')).toHaveTextContent(NOT_DRAFTED);
        expect((await step()).queryByRole('alert')).not.toBeInTheDocument();
      },
    );

    it('keeps waiting through a failed read of the running draft, and fills it once ready', async () => {
      vi.mocked(positioningService.get)
        .mockResolvedValueOnce({ text: null, draft: RUNNING })
        .mockRejectedValueOnce(apiError(502, 'Bad gateway.'))
        .mockResolvedValue({ text: null, draft: READY });
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderOnboarding();
        const textarea = await field();

        await act(() => vi.advanceTimersByTimeAsync(2000));
        expect(textarea).toBeDisabled();
        await act(() => vi.advanceTimersByTimeAsync(2000));

        await waitFor(() => expect(textarea).toHaveValue(DRAFTED));
      } finally {
        vi.useRealTimers();
      }
    });

    it('opens an empty textarea with the reason when reading the running draft keeps failing', async () => {
      vi.mocked(positioningService.get)
        .mockResolvedValueOnce({ text: null, draft: RUNNING })
        .mockRejectedValue(apiError(502, 'Bad gateway.'));
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderOnboarding();
        const textarea = await field();

        for (let read = 1; read < 5; read++) {
          await act(() => vi.advanceTimersByTimeAsync(2000));
        }
        expect(textarea).toBeDisabled();
        await act(() => vi.advanceTimersByTimeAsync(2000));

        await waitFor(() => expect(textarea).toBeEnabled());
        expect((await step()).getByRole('status')).toHaveTextContent(NOT_DRAFTED);
      } finally {
        vi.useRealTimers();
      }
    });

    it('sends the User to the Paywall when reading the draft is refused for want of a Subscription', async () => {
      vi.mocked(positioningService.get)
        .mockResolvedValueOnce({ text: null, draft: null })
        .mockRejectedValue(
          apiError(403, 'This needs a subscription. Subscribe to continue.', {
            code: 'subscription_required',
          }),
        );
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('paywall');

      renderOnboarding();

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });

    it('shows the same draft when the step reopens, without starting another', async () => {
      const { unmount } = await drafted();
      unmount();

      renderOnboarding();

      await waitFor(async () => expect(await field()).toHaveValue(DRAFTED));
      expect(await field()).toBeEnabled();
      expect(positioningService.startDraft).toHaveBeenCalledTimes(1);
    });

    it('gives one line of advice under the heading, and no checklist', async () => {
      await drafted();

      expect(await field()).toHaveAccessibleDescription(ADVICE);
      expect((await step()).queryByText(/^Cover:/)).not.toBeInTheDocument();
    });

    it('offers no way to draft again and says nothing about the draft', async () => {
      await drafted();
      const region = await step();

      expect(region.getAllByRole('button').map((button) => button.textContent)).toEqual([
        'Continue',
      ]);
      expect(region.queryByText(/Drafted from your X profile/)).not.toBeInTheDocument();
    });

    it('puts a full-width Continue under the textarea, with the count between them near the limit', async () => {
      started = { state: 'ready', text: 'a'.repeat(3712), reason: null };
      renderOnboarding();

      const textarea = await field();
      await waitFor(() => expect(textarea).toBeEnabled());
      const count = (await step()).getByText('3,712 / 4,000');
      expect(textarea.compareDocumentPosition(count)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
      expect(count.compareDocumentPosition(continueButton())).toBe(
        Node.DOCUMENT_POSITION_FOLLOWING,
      );
      expect(continueButton()).toHaveClass('w-full');
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

    it('sends the User to the Paywall when finishing is refused for want of a Subscription', async () => {
      vi.mocked(onboardingService.finish).mockRejectedValue(
        apiError(403, 'This needs a subscription. Subscribe to continue.', {
          code: 'subscription_required',
        }),
      );
      await drafted();
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('paywall');

      fireEvent.click(continueButton());

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });

    it.each([
      ['the check that follows fails', () => Promise.reject(new Error('offline'))],
      ['the check still answers the Persona step', () => Promise.resolve('persona' as const)],
    ])(
      'says Continue failed and unlocks the step when finishing is refused and %s',
      async (_case, answer) => {
        vi.mocked(onboardingService.finish).mockRejectedValue(
          apiError(403, 'This needs a subscription. Subscribe to continue.', {
            code: 'subscription_required',
          }),
        );
        await drafted();
        vi.mocked(onboardingService.fetchNextStep).mockImplementation(answer);

        fireEvent.click(continueButton());

        expect(
          await (await step()).findByText("Couldn't continue. Try again."),
        ).toBeInTheDocument();
        expect(currentPath()).toBe('/onboarding');
        expect(continueButton()).toBeEnabled();
        expect(await field()).toBeEnabled();
      },
    );

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
