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
vi.mock('@/services/authorDirectoryService', () => ({
  authorDirectoryService: { list: vi.fn() },
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
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn().mockResolvedValue('paywall') },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { SELLS_PLANS } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import {
  authorDirectoryService,
  type AuthorDirectoryEntry,
} from '@/services/authorDirectoryService';
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
  currentPath,
} from './testing/signedInApp';

function entry(handle: string, name: string, personaCount = 0): AuthorDirectoryEntry {
  return { handle, name, photoUrl: null, personaCount };
}

// Real seed names from `backend/alembic/data/author_seeds.json`, plus Marc Lou, whom a lookup added.
const DIRECTORY: AuthorDirectoryEntry[] = [
  entry('marckohlbrugge', 'Marc Köhlbrugge'),
  entry('levelsio', 'Pieter Levels', 3),
  entry('pmarca', 'Marc Andreessen'),
  entry('paulg', 'Paul Graham', 5),
  entry('karpathy', 'Andrej Karpathy'),
  entry('naval', 'Naval Ravikant', 5),
  entry('jamesclear', 'James Clear'),
  entry('marc_lou', 'Marc Lou', 1),
  entry('byrnehobart', 'Byrne Hobart'),
  entry('taylorotwell', 'Taylor Otwell'),
];

function renderPersona(instance = SELLS_PLANS) {
  return renderSignedIn('/persona', { instance });
}

async function persona() {
  return within(await screen.findByRole('region', { name: 'How your posts sound' }));
}

async function searchField() {
  return (await persona()).findByRole('combobox', { name: 'Find an author' });
}

/** Each row of the open list, as a screen reader reads it. */
function rows(): string[] {
  return screen.queryAllByRole('option').map((option) => {
    const read = option.cloneNode(true) as HTMLElement;
    read.querySelectorAll('[aria-hidden]').forEach((hidden) => hidden.remove());
    return read.textContent ?? '';
  });
}

async function type(query: string) {
  const field = await searchField();
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: query } });
  return field;
}

/** The place markers holding an author, by the handle each shows. */
async function filledSlots() {
  const slots = await (await persona()).findByRole('list', { name: /places taken/ });
  return within(slots)
    .getAllByRole('listitem')
    .filter((slot) => within(slot).queryByText(/^@/) !== null);
}

describe('Persona', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([]);
    vi.mocked(inspirationAuthorService.add).mockReset();
    vi.mocked(inspirationAuthorService.remove).mockReset();
    vi.mocked(inspirationAuthorService.refresh).mockReset();
    vi.mocked(authorDirectoryService.list).mockReset().mockResolvedValue(DIRECTORY);
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(track).mockClear();
  });

  it('says under the "Persona" header that Inspiration authors set how posts sound, not what they say', async () => {
    renderPersona();

    expect(await screen.findByRole('heading', { level: 1, name: 'Persona' })).toBeInTheDocument();
    expect((await persona()).getByText(/never what they say/i)).toBeInTheDocument();
  });

  describe('the slots', () => {
    it('shows one slot per author in order, with when its posts were last fetched, and the rest empty', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderPersona();

      const panel = await persona();
      expect(await panel.findByRole('list', { name: '2 of 3 places taken' })).toBeInTheDocument();
      const slots = await filledSlots();
      expect(slots.map((slot) => within(slot).getByText(/^@/).textContent)).toEqual([
        '@levelsio',
        '@paulg',
      ]);
      expect(within(slots[0]).getByText('Fetched 2 hours ago · 18 posts')).toBeInTheDocument();
      expect(within(slots[1]).getByText('Fetched 5 minutes ago · 20 posts')).toBeInTheDocument();
      expect(panel.getAllByRole('button', { name: 'Add an author' })).toHaveLength(1);
    });

    it('shows three empty slots when the User has no authors, and an empty one focuses the search', async () => {
      renderPersona();

      const panel = await persona();
      const empty = await panel.findAllByRole('button', { name: 'Add an author' });
      expect(empty).toHaveLength(3);

      fireEvent.click(empty[1]);

      expect(await searchField()).toHaveFocus();
    });

    it("shows each author's X photo at the size the slot needs, or their initial when there is none", async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([
        { ...LEVELSIO, photoUrl: 'https://pbs.twimg.com/profile_images/1/levelsio_normal.jpg' },
        PAULG,
      ]);
      renderPersona();

      const [withPhoto, withoutPhoto] = await filledSlots();
      expect(withPhoto.querySelector('img')).toHaveAttribute(
        'src',
        'https://pbs.twimg.com/profile_images/1/levelsio_200x200.jpg',
      );
      expect(withoutPhoto.querySelector('img')).toBeNull();
      expect(within(withoutPhoto).getByText('P')).toBeInTheDocument();
    });

    it("shows each author's name from the Author directory above their handle", async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([
        { ...LEVELSIO, name: 'Pieter Levels' },
        PAULG,
      ]);
      renderPersona();

      const [named, unnamed] = await filledSlots();
      expect(within(named).getByText('Pieter Levels')).toBeInTheDocument();
      expect(within(named).getByText('@levelsio')).toBeInTheDocument();
      expect(within(unnamed).getByText('@paulg')).toBeInTheDocument();
    });

    it("shows an author's initials when their photo fails to load", async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([
        {
          ...LEVELSIO,
          name: 'Pieter Levels',
          photoUrl: 'https://pbs.twimg.com/profile_images/1/gone_normal.jpg',
        },
      ]);
      renderPersona();

      const [slot] = await filledSlots();
      fireEvent.error(slot.querySelector('img')!);

      expect(slot.querySelector('img')).toBeNull();
      expect(within(slot).getByText('PL')).toBeInTheDocument();
    });

    it('shows a spinner and "Reading @handle\'s posts…" in the slot while the author\'s posts are read', async () => {
      vi.mocked(inspirationAuthorService.add).mockReturnValue(new Promise(() => {}));
      renderPersona();

      const field = await type('marc');
      fireEvent.keyDown(field, { key: 'Enter' });

      const slots = (await persona()).getByRole('list', { name: /places taken/ });
      expect(await within(slots).findByText("Reading @marc_lou's posts…")).toBeInTheDocument();
      expect(within(slots).getAllByRole('button', { name: 'Add an author' })).toHaveLength(2);
    });

    it('disables the search once all three places are taken, until one is removed', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG, NAVAL]);
      vi.mocked(inspirationAuthorService.remove).mockResolvedValue(undefined);
      renderPersona();

      const panel = await persona();
      const field = await searchField();
      await waitFor(() => expect(field).toBeDisabled());
      expect(field).toHaveAccessibleDescription(
        'All three places are taken. Remove one to pick another.',
      );
      expect(panel.getByRole('list', { name: '3 of 3 places taken' })).toBeInTheDocument();

      fireEvent.click(panel.getByRole('button', { name: 'Remove @naval' }));

      await waitFor(() => expect(field).toBeEnabled());
      expect(inspirationAuthorService.remove).toHaveBeenCalledWith('naval');
      expect(track).toHaveBeenCalledWith('inspiration_author_removed');
    });

    it('refreshes an author and shows its new fetch time and post count', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      vi.mocked(inspirationAuthorService.refresh).mockResolvedValue({
        handle: 'levelsio',
        lastFetchedAt: new Date().toISOString(),
        postCount: 21,
        name: null,
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

  describe('the author picker', () => {
    it('lists the directory on focus, most picked first and then by name, leaving out the Persona', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([NAVAL]);
      renderPersona();

      const field = await searchField();
      expect(field).toHaveAttribute('placeholder', 'Search by name or @handle');
      await waitFor(() => expect(field).toBeEnabled());
      fireEvent.focus(field);

      await waitFor(() =>
        expect(rows()).toEqual([
          'Paul Graham @paulg',
          'Pieter Levels @levelsio',
          'Marc Lou @marc_lou',
          'Andrej Karpathy @karpathy',
          'Byrne Hobart @byrnehobart',
          'James Clear @jamesclear',
          'Marc Andreessen @pmarca',
          'Marc Köhlbrugge @marckohlbrugge',
          'Taylor Otwell @taylorotwell',
        ]),
      );
    });

    it('shows a skeleton list while the directory loads', async () => {
      vi.mocked(authorDirectoryService.list).mockReturnValue(new Promise(() => {}));
      renderPersona();

      fireEvent.focus(await searchField());

      expect(
        await screen.findByRole('status', { name: 'Loading suggestions' }),
      ).toBeInTheDocument();
    });

    it('says how to look someone up when no directory entry is left to show', async () => {
      vi.mocked(authorDirectoryService.list).mockResolvedValue([]);
      renderPersona();

      fireEvent.focus(await searchField());

      expect(
        await screen.findByText('Type a name or @handle to look someone up on X.'),
      ).toBeInTheDocument();
    });

    // Fuse's threshold is 0.35: "levlsio" scores 0.31 against levelsio, while "foobar" scores 0.38
    // against byrnehobart and "blorft" 0.52 against taylorotwell over the 193 seeds.
    it('finds "levlsio", a typo, as Pieter Levels, with the X lookup last', async () => {
      renderPersona();

      await type('levlsio');

      await waitFor(() =>
        expect(rows()).toEqual(['Pieter Levels @levelsio', 'Look up @levlsio on X']),
      );
    });

    it.each(['foobar', 'blorft'])(
      'offers no directory row for "%s", which is nonsense, only the X lookup',
      async (query) => {
        renderPersona();

        await type(query);

        await waitFor(() => expect(rows()).toEqual([`Look up @${query} on X`]));
      },
    );

    it('ranks an exact handle first and offers no lookup for a handle the directory has', async () => {
      renderPersona();

      await type('@pmarca');

      await waitFor(() => expect(rows()[0]).toBe('Marc Andreessen @pmarca'));
      expect(rows()).not.toContain('Look up @pmarca on X');
    });

    it('offers no X lookup for a query not shaped like a handle', async () => {
      renderPersona();

      await type('paul graham');

      await waitFor(() => expect(rows()).toEqual(['Paul Graham @paulg']));
    });

    it('says nothing matches a query that is neither in the directory nor a handle', async () => {
      renderPersona();

      await type('zq zq');

      expect(
        await screen.findByText('No suggestion matches. Type an @handle to look it up on X.'),
      ).toBeInTheDocument();
      expect(rows()).toEqual([]);
    });

    it('puts directory matches for "marc" first and the X lookup last, and Enter picks Marc Lou', async () => {
      vi.mocked(inspirationAuthorService.add).mockResolvedValue({
        ...LEVELSIO,
        handle: 'marc_lou',
        name: 'Marc Lou',
      });
      renderPersona();

      const field = await type('marc');
      await waitFor(() =>
        expect(rows()).toEqual([
          'Marc Lou @marc_lou',
          'Marc Andreessen @pmarca',
          'Marc Köhlbrugge @marckohlbrugge',
          'Look up @marc on X',
        ]),
      );
      fireEvent.keyDown(field, { key: 'Enter' });

      const [slot] = await filledSlots();
      expect(within(slot).getByText('@marc_lou')).toBeInTheDocument();
      expect(inspirationAuthorService.add).toHaveBeenCalledWith('marc_lou');
      expect(field).toHaveValue('');
      expect(track).toHaveBeenCalledWith('inspiration_author_added');
      expect(track).not.toHaveBeenCalledWith('author_looked_up', expect.anything());
    });

    it('puts the X lookup first for "@marc", and Enter looks @marc up', async () => {
      vi.mocked(inspirationAuthorService.add).mockResolvedValue({
        ...LEVELSIO,
        handle: 'marc',
        name: 'Marc',
      });
      renderPersona();

      const field = await type('@marc');
      await waitFor(() => expect(rows()[0]).toBe('Look up @marc on X'));
      expect(rows()).toContain('Marc Lou @marc_lou');
      fireEvent.keyDown(field, { key: 'Enter' });

      expect(await within((await filledSlots())[0]).findByText('@marc')).toBeInTheDocument();
      expect(inspirationAuthorService.add).toHaveBeenCalledWith('marc');
      expect(track).toHaveBeenCalledWith('author_looked_up', { result: 'found' });
    });

    it('highlights the first row as results change, moves it with ↑ and ↓, and closes on Escape', async () => {
      renderPersona();

      const field = await type('marc');
      await waitFor(() => expect(rows()).toHaveLength(4));
      const options = () => screen.getAllByRole('option');
      expect(field).toHaveAttribute('aria-activedescendant', options()[0].id);
      expect(options()[0]).toHaveAttribute('aria-selected', 'true');

      fireEvent.keyDown(field, { key: 'ArrowDown' });
      fireEvent.keyDown(field, { key: 'ArrowDown' });
      expect(field).toHaveAttribute('aria-activedescendant', options()[2].id);
      fireEvent.keyDown(field, { key: 'ArrowUp' });
      expect(options()[1]).toHaveAttribute('aria-selected', 'true');

      fireEvent.change(field, { target: { value: 'marc a' } });
      await waitFor(() => expect(field).toHaveAttribute('aria-activedescendant', options()[0].id));

      fireEvent.keyDown(field, { key: 'Escape' });
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
      expect(field).toHaveAttribute('aria-expanded', 'false');

      fireEvent.keyDown(field, { key: 'ArrowDown' });
      expect(screen.getByRole('listbox')).toBeInTheDocument();
    });

    it('picks a row with the mouse', async () => {
      vi.mocked(inspirationAuthorService.add).mockResolvedValue({
        ...PAULG,
        name: 'Paul Graham',
      });
      renderPersona();

      fireEvent.focus(await searchField());
      fireEvent.click(await screen.findByRole('option', { name: /Paul Graham/ }));

      await waitFor(() => expect(inspirationAuthorService.add).toHaveBeenCalledWith('paulg'));
      expect(await within((await filledSlots())[0]).findByText('@paulg')).toBeInTheDocument();
    });

    it('announces how many rows match', async () => {
      renderPersona();

      await type('marc');

      expect(await screen.findByRole('status', { name: 'Results' })).toHaveTextContent('4 results');
    });

    it.each([
      [404, "@nobody isn't on X.", 'HANDLE_NOT_ON_X', 'missing'],
      [422, "@nobody is private, so Pumpkit can't read its posts.", 'HANDLE_PRIVATE', 'private'],
      [422, '@nobody has no posts of its own to learn from.', 'HANDLE_HAS_NO_POSTS', 'no_posts'],
      [429, "You've looked up a lot of handles. Try again in 40 minutes.", null, 'limited'],
      [
        429,
        'Looking up new handles is paused for today. Pick from the suggestions or try again tomorrow.',
        null,
        'limited',
      ],
      [409, 'You can have up to 3 Inspiration authors. Remove one to add another.', null, null],
    ])(
      'says under the field why a lookup was refused with a %i, keeping the query',
      async (status, detail, code, result) => {
        vi.mocked(inspirationAuthorService.add).mockRejectedValue(
          apiError(status, detail, code ? { code } : {}),
        );
        renderPersona();

        const field = await type('@nobody');
        await waitFor(() => expect(rows()[0]).toBe('Look up @nobody on X'));
        fireEvent.keyDown(field, { key: 'Enter' });

        await waitFor(() => expect(field).toHaveAccessibleDescription(detail));
        expect(field).toHaveValue('@nobody');
        expect(track).not.toHaveBeenCalledWith('inspiration_author_added');
        if (result) expect(track).toHaveBeenCalledWith('author_looked_up', { result });
        else expect(track).not.toHaveBeenCalledWith('author_looked_up', expect.anything());
      },
    );

    it('says "Couldn\'t load suggestions." when the directory fails, and still looks handles up', async () => {
      vi.mocked(authorDirectoryService.list).mockRejectedValue(apiError(500, 'boom'));
      vi.mocked(inspirationAuthorService.add).mockResolvedValue(LEVELSIO);
      renderPersona();

      const field = await searchField();
      fireEvent.focus(field);
      expect(await screen.findByText("Couldn't load suggestions.")).toBeInTheDocument();

      fireEvent.change(field, { target: { value: '@levelsio' } });
      await waitFor(() => expect(rows()).toEqual(['Look up @levelsio on X']));
      fireEvent.keyDown(field, { key: 'Enter' });

      await waitFor(() => expect(inspirationAuthorService.add).toHaveBeenCalledWith('levelsio'));
    });

    it('sends the User to the Paywall when adding is refused with a 403', async () => {
      vi.mocked(billingService.fetchBillingMe)
        .mockResolvedValueOnce(SUBSCRIBED)
        .mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(inspirationAuthorService.add).mockRejectedValue(
        apiError(403, 'This needs a subscription. Subscribe to continue.'),
      );
      renderPersona();

      const field = await type('paulg');
      await waitFor(() => expect(rows()[0]).toBe('Paul Graham @paulg'));
      fireEvent.keyDown(field, { key: 'Enter' });

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
    });
  });
});
