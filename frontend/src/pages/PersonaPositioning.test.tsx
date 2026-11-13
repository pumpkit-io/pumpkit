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
  positioningService: { get: vi.fn(), save: vi.fn() },
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
import { positioningService } from '@/services/positioningService';
import {
  NOT_SUBSCRIBED,
  SUBSCRIBED,
  apiError,
  currentPath,
  renderSignedIn,
} from './testing/signedInApp';

const SAVED =
  "I'm a solo founder. I post about bootstrapping for people starting their first SaaS.";

async function panel() {
  return within(await screen.findByRole('region', { name: 'Who you are on X' }));
}

async function field() {
  return (await panel()).findByRole('textbox', { name: 'Who you are on X' });
}

describe('Persona: the Positioning panel', () => {
  beforeEach(() => {
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(positioningService.get).mockReset().mockResolvedValue(null);
    vi.mocked(positioningService.save).mockReset();
    vi.mocked(track).mockClear();
  });

  it("shows the User's saved Positioning in the textarea, above the Inspiration authors", async () => {
    vi.mocked(positioningService.get).mockResolvedValue({
      text: SAVED,
      savedAt: '2026-10-10T12:00:30Z',
    });
    renderSignedIn('/persona');

    await waitFor(async () => expect(await field()).toHaveValue(SAVED));
    const regions = screen
      .getAllByRole('region')
      .map((region) => region.getAttribute('aria-labelledby'));
    const headings = regions.map((id) => (id ? document.getElementById(id)?.textContent : null));
    expect(headings).toEqual(['Who you are on X', 'How your posts sound']);
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
      .mockResolvedValue({ text: SAVED, savedAt: '2026-10-10T12:00:30Z' });
    renderSignedIn('/persona');

    const region = await panel();
    expect(await region.findByRole('alert')).toHaveTextContent("Couldn't load your positioning.");
    expect(region.queryByRole('textbox')).not.toBeInTheDocument();

    fireEvent.click(region.getByRole('button', { name: 'Try again' }));

    await waitFor(async () => expect(await field()).toHaveValue(SAVED));
  });

  it('saves what the User wrote, says so, and waits for the next edit to offer Save again', async () => {
    vi.mocked(positioningService.save).mockResolvedValue({
      text: 'I post about pricing.',
      savedAt: '2026-10-10T13:00:30Z',
    });
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
    vi.mocked(positioningService.get).mockResolvedValue({
      text: SAVED,
      savedAt: '2026-10-10T12:00:30Z',
    });
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

  it('shows "Saving…" and disables the button while a save is on its way', async () => {
    vi.mocked(positioningService.save).mockReturnValue(new Promise(() => {}));
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    fireEvent.click((await panel()).getByRole('button', { name: 'Save' }));

    expect(await (await panel()).findByRole('button', { name: 'Saving…' })).toBeDisabled();
  });

  it.each([
    [
      apiError(429, 'Too many requests. Try again in a minute.'),
      'Too many requests. Try again in a minute.',
    ],
    [apiError(500, null as unknown as string), "Couldn't save your positioning. Try again."],
  ])('says under the textarea why a save failed, keeping the text', async (failure, message) => {
    vi.mocked(positioningService.save).mockRejectedValue(failure);
    renderSignedIn('/persona');

    const textarea = await field();
    await waitFor(() => expect(textarea).toBeEnabled());
    fireEvent.change(textarea, { target: { value: 'I post about pricing.' } });
    const region = await panel();
    fireEvent.click(region.getByRole('button', { name: 'Save' }));

    expect(await region.findByRole('alert')).toHaveTextContent(message);
    expect(textarea).toHaveValue('I post about pricing.');
    expect(textarea).toHaveAccessibleDescription(new RegExp(`^${message.replace(/[.']/g, '.')}`));
    expect(region.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(region.queryByText('Saved')).not.toBeInTheDocument();
    expect(track).not.toHaveBeenCalledWith('positioning_saved');
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

  it('sends the User to the Paywall when saving is refused with a 403', async () => {
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
});
