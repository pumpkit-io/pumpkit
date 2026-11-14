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
    fetchPlans: vi.fn().mockResolvedValue({
      plans: [],
      termsVersion: '2026-10-11',
      allowance: { generations: null, xPosts: null, linkXPosts: null },
      trial: null,
    }),
  },
}));
vi.mock('@/services/positioningService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/positioningService')>()),
  positioningService: { get: vi.fn(), save: vi.fn(), draft: vi.fn() },
}));
vi.mock('@/services/inspirationAuthorService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/inspirationAuthorService')>()),
  inspirationAuthorService: { list: vi.fn().mockResolvedValue([]) },
}));
vi.mock('@/services/authorDirectoryService', () => ({
  authorDirectoryService: { list: vi.fn().mockResolvedValue([]) },
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
  },
}));
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn().mockResolvedValue('paywall') },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { track } from '@/lib/analytics';
import { billingService } from '@/services/billingService';
import { positioningService, type Positioning } from '@/services/positioningService';
import {
  NOT_SUBSCRIBED,
  SUBSCRIBED,
  apiError,
  currentPath,
  renderSignedIn,
} from './testing/signedInApp';

const SAVED =
  "I'm a solo founder. I post about bootstrapping for people starting their first SaaS.";
const DRAFTED = "I'm a solo founder building a pricing tool. I post about pricing for founders.";
/** What a User who saved no Positioning and has drafts left reads. */
const NONE = { text: null, canDraft: true };
const DRAFT_AGAIN = 'Draft again from my X profile';

/** The 422 FastAPI answers when `PositioningSaveRequest` refuses the text: `detail` is a list. */
function textRefused() {
  return Object.assign(new Error('Request failed with status code 422'), {
    isAxiosError: true,
    response: {
      status: 422,
      data: {
        detail: [
          {
            type: 'value_error',
            loc: ['body', 'text'],
            msg: 'Value error, A positioning can be up to 4,000 characters.',
            input: 'I post about pricing.',
            ctx: { error: {} },
          },
        ],
      },
    },
  });
}

async function panel() {
  return within(await screen.findByRole('region', { name: 'Who you are on X' }));
}

async function field() {
  return (await panel()).findByRole('textbox', { name: 'Who you are on X' });
}

describe('Persona: the Positioning panel', () => {
  beforeEach(() => {
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(positioningService.get).mockReset().mockResolvedValue(NONE);
    vi.mocked(positioningService.draft).mockReset();
    vi.mocked(positioningService.save).mockReset();
    vi.mocked(track).mockClear();
  });

  it("shows the User's saved Positioning in the textarea, above the Inspiration authors", async () => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    renderSignedIn('/persona');

    await waitFor(async () => expect(await field()).toHaveValue(SAVED));
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings.slice(0, 2)).toEqual(['Who you are on X', 'How your posts sound']);
  });

  it('names the five things a Positioning covers under the textarea', async () => {
    renderSignedIn('/persona');

    expect(await field()).toHaveAccessibleDescription(
      'Cover: who you are · what you post about · who you write for · what you post for · what you can point to',
    );
  });

  it('opens an empty textarea with Save disabled for a User with no Positioning', async () => {
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    expect(textarea).toHaveValue('');
    expect((await panel()).getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('disables the textarea and Save while the Positioning loads', async () => {
    vi.mocked(positioningService.get).mockReturnValue(new Promise(() => {}));
    renderSignedIn('/persona');

    const textarea = await field();
    expect(textarea).toBeDisabled();
    expect(textarea).toHaveAttribute('placeholder', 'Loading your positioning…');
    expect((await panel()).getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it("says the Positioning couldn't be loaded, and Try again loads it", async () => {
    vi.mocked(positioningService.get)
      .mockRejectedValueOnce(apiError(500, 'boom'))
      .mockResolvedValue({ text: SAVED, canDraft: true });
    renderSignedIn('/persona');

    const region = await panel();
    expect(await region.findByRole('alert')).toHaveTextContent("Couldn't load your positioning.");
    expect(region.queryByRole('textbox')).not.toBeInTheDocument();

    fireEvent.click(region.getByRole('button', { name: 'Try again' }));

    await waitFor(async () => expect(await field()).toHaveValue(SAVED));
  });

  it('saves what the User wrote, says so, and waits for the next edit to offer Save again', async () => {
    vi.mocked(positioningService.save).mockResolvedValue({ text: 'I post about pricing.' });
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: '  I post about pricing.\n' } });
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: 'Save' }));

    expect(await region.findByText('Saved')).toBeInTheDocument();
    expect(positioningService.save).toHaveBeenCalledWith('  I post about pricing.\n');
    expect(textarea).toHaveValue('I post about pricing.');
    expect(region.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(track).toHaveBeenCalledWith('positioning_saved');

    fireEvent.change(textarea, { target: { value: 'I post about pricing and churn.' } });

    expect(region.queryByText('Saved')).not.toBeInTheDocument();
    expect(region.getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('keeps Save disabled while the text is blank or the same as what is saved', async () => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(SAVED));
    const save = (await panel()).getByRole('button', { name: 'Save' });
    expect(save).toBeDisabled();

    fireEvent.change(textarea, { target: { value: '   ' } });
    expect(save).toBeDisabled();

    fireEvent.change(textarea, { target: { value: `${SAVED} ` } });
    expect(save).toBeDisabled();
  });

  it.each(['\0', ' \ud800 ', '\x1f\x85'])(
    'keeps Save disabled for text the backend would find blank (%j)',
    async (blank) => {
      renderSignedIn('/persona');

      const textarea = await field();
      await waitFor(() => expect(textarea).toBeEnabled());
      fireEvent.change(textarea, { target: { value: blank } });

      expect((await panel()).getByRole('button', { name: 'Save' })).toBeDisabled();
    },
  );

  it('shows "Saving…" and disables the button while a save is on its way', async () => {
    vi.mocked(positioningService.save).mockReturnValue(new Promise(() => {}));
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    fireEvent.click((await panel()).getByRole('button', { name: 'Save' }));

    expect(await (await panel()).findByRole('button', { name: 'Saving…' })).toBeDisabled();
  });

  it('keeps what the User types while a save is on its way', async () => {
    let finishSave: (positioning: Positioning) => void = () => {};
    vi.mocked(positioningService.save).mockReturnValue(
      new Promise((resolve) => {
        finishSave = resolve;
      }),
    );
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: 'Save' }));
    await region.findByRole('button', { name: 'Saving…' });
    fireEvent.change(textarea, { target: { value: 'I post about pricing and churn.' } });

    finishSave({ text: 'I post about pricing.' });

    await waitFor(() => expect(region.getByRole('button', { name: 'Save' })).toBeEnabled());
    expect(textarea).toHaveValue('I post about pricing and churn.');
    expect(region.queryByText('Saved')).not.toBeInTheDocument();
  });

  it.each([
    {
      failure: apiError(429, 'Too many requests. Try again in a minute.'),
      message: 'Too many requests. Try again in a minute.',
      described: /^Too many requests\. Try again in a minute\. Cover:/,
    },
    {
      failure: Object.assign(new Error('Network Error'), { isAxiosError: true }),
      message: "Couldn't save your positioning. Try again.",
      described: /^Couldn't save your positioning\. Try again\. Cover:/,
    },
  ])('says under the textarea why a save failed, keeping the text', async (failed) => {
    const { failure, message, described } = failed;
    vi.mocked(positioningService.save).mockRejectedValue(failure);
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: 'Save' }));

    expect(await region.findByRole('alert')).toHaveTextContent(message);
    expect(textarea).toHaveValue('I post about pricing.');
    expect(textarea).toHaveAccessibleDescription(described);
    expect(textarea).not.toHaveAttribute('aria-invalid');
    expect(region.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(region.queryByText('Saved')).not.toBeInTheDocument();
    expect(track).not.toHaveBeenCalledWith('positioning_saved');
  });

  it('marks the textarea invalid when the server refuses the text, until the next edit', async () => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    vi.mocked(positioningService.save).mockRejectedValue(textRefused());
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(SAVED));
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: 'Save' }));

    expect(await region.findByRole('alert')).toHaveTextContent(
      "That text can't be saved as your positioning. Change it and save again.",
    );
    expect(textarea).toHaveAttribute('aria-invalid', 'true');

    fireEvent.change(textarea, { target: { value: SAVED } });

    expect(region.queryByRole('alert')).not.toBeInTheDocument();
    expect(textarea).not.toHaveAttribute('aria-invalid');
    expect(textarea).toHaveAccessibleDescription(/^Cover:/);
  });

  it('says why a save was refused with a 403 that is not for want of a Subscription', async () => {
    vi.mocked(positioningService.save).mockRejectedValue(
      apiError(403, 'Your account is suspended.'),
    );
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: 'Save' }));

    expect(await region.findByRole('alert')).toHaveTextContent('Your account is suspended.');
    expect(currentPath()).toBe('/persona');
  });

  it('shows the character count once the text nears 4,000 characters, and stops typing there', async () => {
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    expect(textarea).toHaveAttribute('maxlength', '4000');
    fireEvent.change(textarea, { target: { value: 'a'.repeat(3599) } });
    expect((await panel()).queryByText(/\/ 4,000/)).not.toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: 'a'.repeat(3600) } });

    expect((await panel()).getByText('3,600 / 4,000')).toBeInTheDocument();
  });

  it('counts an emoji as one character, as the backend does, and leaves room to edit', async () => {
    const emoji = '🎃'.repeat(4000);
    vi.mocked(positioningService.get).mockResolvedValue({ text: emoji, canDraft: true });
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(emoji));

    expect((await panel()).getByText('4,000 / 4,000')).toBeInTheDocument();
    expect(textarea).toHaveAttribute('maxlength', '8000');
  });

  it('sends the User to the Paywall when saving is refused for want of a Subscription', async () => {
    vi.mocked(billingService.fetchBillingMe)
      .mockResolvedValueOnce(SUBSCRIBED)
      .mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(positioningService.save).mockRejectedValue(
      apiError(403, 'This needs a subscription. Subscribe to continue.'),
    );
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    fireEvent.click((await panel()).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(currentPath()).toBe('/subscribe'));
  });

  it('fills the textarea with a draft from the X profile and saves nothing', async () => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    vi.mocked(positioningService.draft).mockResolvedValue({
      text: DRAFTED,
      reason: null,
      canDraft: true,
    });
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(SAVED));
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: DRAFT_AGAIN }));

    await waitFor(() => expect(textarea).toHaveValue(DRAFTED));
    expect(region.getByRole('status')).toHaveTextContent(
      'Drafted from your X profile. Save to keep it.',
    );
    expect(positioningService.save).not.toHaveBeenCalled();
    expect(region.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(region.getByRole('button', { name: DRAFT_AGAIN })).toBeEnabled();
  });

  it('drops the note about the draft once the User edits it', async () => {
    vi.mocked(positioningService.draft).mockResolvedValue({
      text: DRAFTED,
      reason: null,
      canDraft: true,
    });
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: DRAFT_AGAIN }));
    await region.findByText('Drafted from your X profile. Save to keep it.');

    fireEvent.change(textarea, { target: { value: `${DRAFTED} I sell a course.` } });

    expect(region.queryByText(/Drafted from your X profile/)).not.toBeInTheDocument();
  });

  it('shows "Reading your X profile…" and disables the panel while a draft is on its way', async () => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    vi.mocked(positioningService.draft).mockReturnValue(new Promise(() => {}));
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(SAVED));
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: DRAFT_AGAIN }));

    await waitFor(() => expect(textarea).toBeDisabled());
    expect(textarea).toHaveValue('');
    expect(textarea).toHaveAttribute('placeholder', 'Reading your X profile…');
    expect(region.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(region.getByRole('button', { name: DRAFT_AGAIN })).toBeDisabled();
  });

  it('keeps the text and says why when no draft could be made', async () => {
    const reason = "We couldn't read your X profile. Write it yourself, a few sentences is enough.";
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    vi.mocked(positioningService.draft).mockResolvedValue({ text: null, reason, canDraft: true });
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(SAVED));
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: DRAFT_AGAIN }));

    expect(await region.findByRole('alert')).toHaveTextContent(reason);
    expect(textarea).toHaveAccessibleDescription(new RegExp(`^${reason}`));
    expect(textarea).toHaveValue(SAVED);
    expect(textarea).toBeEnabled();
    expect(region.getByRole('button', { name: DRAFT_AGAIN })).toBeEnabled();
  });

  it.each([
    {
      failure: apiError(500, 'Something went wrong. Please try again later.'),
      message: 'Something went wrong. Please try again later.',
    },
    {
      failure: Object.assign(new Error('Network Error'), { isAxiosError: true }),
      message: "We couldn't draft your positioning. Write it yourself, a few sentences is enough.",
    },
  ])('keeps the text and says so when the draft request fails', async ({ failure, message }) => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    vi.mocked(positioningService.draft).mockRejectedValue(failure);
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(SAVED));
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: DRAFT_AGAIN }));

    expect(await region.findByRole('alert')).toHaveTextContent(message);
    expect(textarea).toHaveValue(SAVED);
    expect(region.getByRole('button', { name: DRAFT_AGAIN })).toBeEnabled();
  });

  it('disables the draft button with "You can draft again tomorrow." for a User at the limit', async () => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: false });
    renderSignedIn('/persona');

    await waitFor(async () => expect(await field()).toHaveValue(SAVED));
    const button = (await panel()).getByRole('button', { name: DRAFT_AGAIN });

    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription('You can draft again tomorrow.');
  });

  it('says nothing about tomorrow while the User has drafts left', async () => {
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    const region = await panel();

    expect(region.getByRole('button', { name: DRAFT_AGAIN })).toBeEnabled();
    expect(region.queryByText('You can draft again tomorrow.')).not.toBeInTheDocument();
  });

  it('disables the draft button once the last draft of the day is used', async () => {
    vi.mocked(positioningService.draft).mockResolvedValue({
      text: DRAFTED,
      reason: null,
      canDraft: false,
    });
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: DRAFT_AGAIN }));

    await waitFor(() => expect(textarea).toHaveValue(DRAFTED));
    expect(region.getByRole('button', { name: DRAFT_AGAIN })).toBeDisabled();
    expect(region.getByText('You can draft again tomorrow.')).toBeInTheDocument();
  });

  it('disables the draft button when the server says the limit is reached', async () => {
    vi.mocked(positioningService.get).mockResolvedValue({ text: SAVED, canDraft: true });
    vi.mocked(positioningService.draft).mockRejectedValue(
      apiError(429, 'You can draft again tomorrow.'),
    );
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toHaveValue(SAVED));
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: DRAFT_AGAIN }));

    expect(await region.findByText('You can draft again tomorrow.')).toBeInTheDocument();
    expect(region.getByRole('button', { name: DRAFT_AGAIN })).toBeDisabled();
    expect(textarea).toHaveValue(SAVED);
  });

  it('sends the User to the Paywall when a draft is refused for want of a Subscription', async () => {
    vi.mocked(billingService.fetchBillingMe)
      .mockResolvedValueOnce(SUBSCRIBED)
      .mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(positioningService.draft).mockRejectedValue(
      apiError(403, 'This needs a subscription. Subscribe to continue.'),
    );
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.click((await panel()).getByRole('button', { name: DRAFT_AGAIN }));

    await waitFor(() => expect(currentPath()).toBe('/subscribe'));
  });
});
