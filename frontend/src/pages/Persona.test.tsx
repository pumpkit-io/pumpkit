import { fireEvent, screen, waitFor, within } from '@testing-library/react';
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
    fetchPlans: vi.fn().mockResolvedValue({
      plans: [],
      termsVersion: '2026-10-11',
      allowance: { generations: null, xPosts: null, linkXPosts: null },
      trial: null,
    }),
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
vi.mock('@/services/xConnectionService', () => ({
  xConnectionService: {
    get: vi.fn(),
    startAuthorization: vi.fn(),
    complete: vi.fn(),
    disconnect: vi.fn(),
  },
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
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { SELLS_PLANS } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { xConnectionService } from '@/services/xConnectionService';
import {
  LEVELSIO,
  NAVAL,
  NOT_SUBSCRIBED,
  PAULG,
  SUBSCRIBED,
  apiError,
  renderSignedIn,
} from './testing/signedInApp';

function renderPersona(instance = SELLS_PLANS) {
  return renderSignedIn('/persona', { instance });
}

async function persona() {
  return within(await screen.findByRole('region', { name: 'How your posts sound' }));
}

describe('Persona', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([]);
    vi.mocked(inspirationAuthorService.add).mockReset();
    vi.mocked(inspirationAuthorService.remove).mockReset();
    vi.mocked(inspirationAuthorService.refresh).mockReset();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(track).mockClear();
  });

  it('says under the "Persona" header that Inspiration authors set how posts sound, not what they say', async () => {
    renderPersona();

    expect(await screen.findByRole('heading', { level: 1, name: 'Persona' })).toBeInTheDocument();
    expect((await persona()).getByText(/never what they say/i)).toBeInTheDocument();
  });

  it('marks how many of the three places are taken', async () => {
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
    renderPersona();

    const panel = await persona();
    expect(await panel.findByRole('img', { name: '2 of 3 places taken' })).toBeInTheDocument();
  });

  it('disables adding with a note to remove one once all three places are taken', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG, NAVAL]);
    renderPersona();

    const panel = await persona();
    const field = await panel.findByLabelText('X handle');
    expect(field).toBeDisabled();
    expect(field).toHaveAccessibleDescription(/remove an inspiration author to add another/i);
    expect(panel.getByRole('button', { name: 'Add author' })).toBeDisabled();
    expect(panel.getByRole('img', { name: '3 of 3 places taken' })).toBeInTheDocument();

    fireEvent.click(panel.getByRole('button', { name: 'Remove @naval' }));

    await waitFor(() => expect(field).toBeEnabled());
  });

  it('lists the authors in order with when their posts were last fetched and how many are stored', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
    renderPersona();

    const panel = await persona();
    const items = await panel.findAllByRole('listitem');
    expect(items.map((item) => within(item).getByText(/^@/).textContent)).toEqual([
      '@levelsio',
      '@paulg',
    ]);
    expect(within(items[0]).getByText('Fetched 2 hours ago · 18 posts')).toBeInTheDocument();
    expect(within(items[1]).getByText('Fetched 5 minutes ago · 20 posts')).toBeInTheDocument();
  });

  it("shows each author's X photo left of their handle, or their initial when there is none", async () => {
    const photo = 'https://pbs.twimg.com/profile_images/1/levelsio_normal.jpg';
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([
      { ...LEVELSIO, photoUrl: photo },
      PAULG,
    ]);
    renderPersona();

    const [withPhoto, withoutPhoto] = await (await persona()).findAllByRole('listitem');
    expect(withPhoto.querySelector('img')).toHaveAttribute('src', photo);
    expect(withoutPhoto.querySelector('img')).toBeNull();
    expect(within(withoutPhoto).getByText('P')).toBeInTheDocument();
  });

  it("shows an author's initial when their photo fails to load", async () => {
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([
      { ...LEVELSIO, photoUrl: 'https://pbs.twimg.com/profile_images/1/gone_normal.jpg' },
    ]);
    renderPersona();

    const [row] = await (await persona()).findAllByRole('listitem');
    fireEvent.error(row.querySelector('img')!);

    expect(row.querySelector('img')).toBeNull();
    expect(within(row).getByText('L')).toBeInTheDocument();
  });

  it('says how to start when the User has no authors', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
    renderPersona();

    const panel = await persona();
    expect(await panel.findByText(/no inspiration authors yet/i)).toBeInTheDocument();
  });

  it('adds a handle, shows it in the list and clears the field', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.add).mockResolvedValue(LEVELSIO);
    renderPersona();

    const panel = await persona();
    const field = await panel.findByLabelText('X handle');
    fireEvent.change(field, { target: { value: '@LevelsIO' } });
    fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

    expect(await panel.findByText('@levelsio')).toBeInTheDocument();
    expect(inspirationAuthorService.add).toHaveBeenCalledWith('@LevelsIO');
    expect(field).toHaveValue('');
    expect(track).toHaveBeenCalledWith('inspiration_author_added');
  });

  it.each([
    [404, "@nobody doesn't exist on X."],
    [422, '@nobody has no original posts to learn from.'],
    [409, 'You can have up to 3 Inspiration authors. Remove one to add another.'],
  ])(
    'says why a handle was refused with a %i and keeps it in the field',
    async (status, detail) => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.add).mockRejectedValue(apiError(status, detail));
      renderPersona();

      const panel = await persona();
      const field = await panel.findByLabelText('X handle');
      fireEvent.change(field, { target: { value: 'nobody' } });
      fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

      expect(await panel.findByRole('alert')).toHaveTextContent(detail);
      expect(field).toHaveValue('nobody');
      expect(track).not.toHaveBeenCalledWith('inspiration_author_added');
    },
  );

  it('removes an author from the list', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
    vi.mocked(inspirationAuthorService.remove).mockResolvedValue(undefined);
    renderPersona();

    const panel = await persona();
    fireEvent.click(await panel.findByRole('button', { name: 'Remove @levelsio' }));

    await waitFor(() => expect(panel.queryByText('@levelsio')).not.toBeInTheDocument());
    expect(panel.getByText('@paulg')).toBeInTheDocument();
    expect(inspirationAuthorService.remove).toHaveBeenCalledWith('levelsio');
    expect(track).toHaveBeenCalledWith('inspiration_author_removed');
  });

  it('shows a User who is not Subscribed their authors and a prompt that leads to Choose a plan', async () => {
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
    renderPersona();

    const panel = await persona();
    expect(await panel.findByText('@levelsio')).toBeInTheDocument();
    expect(await panel.findByText(/needs a subscription/i)).toBeInTheDocument();
    expect(panel.queryByLabelText('X handle')).not.toBeInTheDocument();
    expect(panel.queryByRole('button', { name: 'Remove @levelsio' })).not.toBeInTheDocument();
    expect(panel.queryByRole('button', { name: 'Refresh @levelsio' })).not.toBeInTheDocument();

    fireEvent.click(panel.getByRole('link', { name: 'Subscribe' }));
    expect(await screen.findByRole('region', { name: 'Choose a plan' })).toBeInTheDocument();
  });

  it('shows the prompt to subscribe when adding is refused with a 403', async () => {
    vi.mocked(billingService.fetchBillingMe)
      .mockResolvedValueOnce(SUBSCRIBED)
      .mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(inspirationAuthorService.add).mockRejectedValue(
      apiError(403, 'This needs a subscription. Subscribe to continue.'),
    );
    renderPersona();

    const panel = await persona();
    fireEvent.change(await panel.findByLabelText('X handle'), { target: { value: 'levelsio' } });
    fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

    expect(await panel.findByRole('link', { name: 'Subscribe' })).toBeInTheDocument();
  });

  it('refreshes an author and shows its new fetch time and post count', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
    vi.mocked(inspirationAuthorService.refresh).mockResolvedValue({
      handle: 'levelsio',
      lastFetchedAt: new Date().toISOString(),
      postCount: 21,
      photoUrl: null,
    });
    renderPersona();

    const panel = await persona();
    fireEvent.click(await panel.findByRole('button', { name: 'Refresh @levelsio' }));

    expect(await panel.findByText('Fetched just now · 21 posts')).toBeInTheDocument();
    expect(inspirationAuthorService.refresh).toHaveBeenCalledWith('levelsio');
    expect(track).toHaveBeenCalledWith('inspiration_authors_refreshed');
  });

  it('says when an author can be refreshed again after a refresh within the day', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 9, 5, 16, 0));
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
    const retryAt = new Date(2026, 9, 6, 15, 42);
    vi.mocked(inspirationAuthorService.refresh).mockRejectedValue(
      apiError(429, '@levelsio was fetched less than a day ago.', {
        retry_at: retryAt.toISOString(),
      }),
    );
    renderPersona();

    const panel = await persona();
    fireEvent.click(await panel.findByRole('button', { name: 'Refresh @levelsio' }));

    expect(
      await panel.findByText(
        '@levelsio was fetched less than a day ago. You can refresh it again tomorrow at 3:42 PM.',
      ),
    ).toBeInTheDocument();
    expect(panel.queryByRole('alert')).not.toBeInTheDocument();
    expect(track).not.toHaveBeenCalledWith('inspiration_authors_refreshed');
  });
});
