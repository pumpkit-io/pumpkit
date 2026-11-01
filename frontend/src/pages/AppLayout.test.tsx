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
    fetchPlans: vi.fn(),
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
vi.mock('@/services/postService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/postService')>()),
  postService: {
    list: vi.fn().mockResolvedValue({
      posts: [],
      counts: { draft: 0, scheduled: 0, published: 0, failed: 0 },
      nextOffset: null,
    }),
    get: vi.fn(),
    start: vi.fn(),
    addVersion: vi.fn(),
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
vi.mock('@/services/scheduledPostService', () => ({
  scheduledPostService: {
    pastCommunities: vi.fn().mockResolvedValue([]),
    postNow: vi.fn(),
    schedule: vi.fn(),
    lookUpCommunity: vi.fn(),
  },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { SELLS_PLANS, WITH_OPERATOR } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { postService, type PostDetail } from '@/services/postService';
import { xConnectionService } from '@/services/xConnectionService';
import {
  LEVELSIO,
  NOT_SUBSCRIBED,
  NO_POSTS,
  PAULG,
  SUBSCRIBED,
  renderSignedIn,
} from './testing/signedInApp';

const POST: PostDetail = {
  id: 'post_01',
  brief: 'ship small things',
  text: {
    format: 'post',
    parts: [{ text: 'the final text', charCount: 14, charLimit: 280 }],
    versionNumber: 1,
    edited: false,
  },
  versions: [
    {
      id: 'version_attempt_01',
      number: 1,
      feedback: null,
      format: 'post',
      parts: [{ text: 'the final text', charCount: 14, charLimit: 280 }],
      createdAt: '2026-10-10T12:00:30Z',
    },
  ],
  status: 'draft',
  scheduledPost: null,
};

async function sidebar() {
  return within(await screen.findByRole('navigation', { name: 'Main' }));
}

function currentPath() {
  return screen.getByRole('status', { name: 'Current path' }).textContent;
}

function newPostShortcut(target: Element | Window = window) {
  fireEvent.keyDown(target, { key: 'O', ctrlKey: true, shiftKey: true });
}

/** A Subscribed User with one Inspiration author, on a written Post's page. */
async function withPostOnScreen() {
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
  vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
  vi.mocked(postService.get).mockResolvedValue(POST);
  renderSignedIn('/posts/post_01');
  await screen.findByRole('article', { name: 'Text' });
}

const NO_CAPS = {
  allowance: { generations: null, xPosts: null, linkXPosts: null },
  trial: null,
  topUp: null,
};

describe('The signed-in shell', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(billingService.fetchPlans)
      .mockReset()
      .mockResolvedValue({ plans: [], termsVersion: '2026-10-11', ...NO_CAPS });
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([]);
    vi.mocked(postService.start).mockReset();
    vi.mocked(postService.list).mockReset().mockResolvedValue(NO_POSTS);
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(track).mockClear();
  });

  describe('Wordmark font preview', () => {
    it('sets every page and dialog in the wordmark font while the switch is on', async () => {
      const { unmount } = renderSignedIn('/posts/new');
      const fontSwitch = await screen.findByRole('switch', { name: 'Wordmark font' });
      const root = document.documentElement;

      expect(root).not.toHaveClass('font-wordmark-preview');
      fireEvent.click(fontSwitch);
      expect(root).toHaveClass('font-wordmark-preview');
      fireEvent.click(fontSwitch);
      expect(root).not.toHaveClass('font-wordmark-preview');

      fireEvent.click(fontSwitch);
      unmount();
      expect(root).not.toHaveClass('font-wordmark-preview');
    });
  });

  describe('Sidebar', () => {
    it('links to New post, Posts, Persona and Settings, marking the page the User is on', async () => {
      renderSignedIn('/persona');

      const nav = await sidebar();
      const links = nav.getAllByRole('link');
      expect(links.map((link) => link.getAttribute('href'))).toEqual([
        '/new',
        '/posts',
        '/persona',
        '/settings',
      ]);
      expect(nav.getByRole('link', { name: 'Persona' })).toHaveAttribute('aria-current', 'page');
      expect(nav.getByRole('link', { name: 'New post' })).not.toHaveAttribute('aria-current');

      fireEvent.click(nav.getByRole('link', { name: 'Posts' }));

      expect(await screen.findByRole('heading', { level: 1, name: 'Posts' })).toBeInTheDocument();
      expect(nav.getByRole('link', { name: 'Posts' })).toHaveAttribute('aria-current', 'page');
    });

    it('shows Persona as a plain link, without counting its Inspiration authors', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderSignedIn('/new');

      const nav = await sidebar();
      await waitFor(() => expect(inspirationAuthorService.list).toHaveBeenCalled());
      expect(nav.getByRole('link', { name: 'Persona' })).toHaveTextContent(/^Persona$/);
    });

    it('shows the number of Failed Posts in a badge on Posts', async () => {
      vi.mocked(postService.list).mockResolvedValue({
        posts: [],
        counts: { draft: 4, scheduled: 2, published: 9, failed: 3 },
        nextOffset: null,
      });
      renderSignedIn('/new');

      const posts = await (await sidebar()).findByRole('link', { name: 'Posts, 3 failed' });
      expect(posts).toHaveTextContent('3');
    });

    it('shows no badge on Posts while no Post has Failed', async () => {
      renderSignedIn('/new');

      const nav = await sidebar();
      await waitFor(() => expect(postService.list).toHaveBeenCalled());
      expect(nav.getByRole('link', { name: 'Posts' })).toHaveTextContent(/^Posts$/);
    });

    it("shows the User's name, X handle and Plan in the user card", async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(billingService.fetchPlans).mockResolvedValue({
        plans: [
          {
            key: 'pumpkit_pro_monthly',
            productName: 'Pumpkit Pro',
            amount: 900,
            currency: 'eur',
            interval: 'month',
            intervalCount: 1,
          },
        ],
        termsVersion: '2026-10-11',
        ...NO_CAPS,
      });
      vi.mocked(xConnectionService.get).mockResolvedValue({
        handle: 'ada',
        charLimit: 280,
        needsReconnect: false,
        scheduledPostsWaiting: 0,
        photoUrl: null,
        offerPhoto: false,
      });
      renderSignedIn('/new');

      const card = within(await screen.findByRole('link', { name: /^Your account/ }));
      expect(await card.findByText('Ada Lovelace')).toBeInTheDocument();
      expect(await card.findByText('@ada')).toBeInTheDocument();
      expect(await card.findByText('Pumpkit Pro')).toBeInTheDocument();
    });

    it('says "Subscribed" in the user card when the Plan has no name to show', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderSignedIn('/new');

      const card = within(await screen.findByRole('link', { name: /^Your account/ }));
      expect(await card.findByText('Subscribed')).toBeInTheDocument();
    });

    it('shows no Plan in the user card on an Instance that sells no Plans', async () => {
      renderSignedIn('/new', { instance: { ...SELLS_PLANS, sells_plans: false } });

      const card = within(await screen.findByRole('link', { name: /^Your account/ }));
      expect(await card.findByText('Ada Lovelace')).toBeInTheDocument();
      expect(card.queryByText('No subscription')).not.toBeInTheDocument();
    });

    it('opens Settings from the user card', async () => {
      renderSignedIn('/new');

      fireEvent.click(await screen.findByRole('link', { name: /^Your account/ }));

      expect(currentPath()).toBe('/settings');
      expect(screen.queryByRole('button', { name: 'User menu' })).not.toBeInTheDocument();
    });

    it('has no collapse toggle', async () => {
      renderSignedIn('/new');
      await sidebar();

      expect(screen.queryByRole('button', { name: 'Close sidebar' })).not.toBeInTheDocument();
      expect(screen.queryByRole('navigation', { name: 'Sidebar rail' })).not.toBeInTheDocument();
    });

    it('leaves the legal links to the Settings footer', async () => {
      renderSignedIn('/new', { instance: WITH_OPERATOR });
      await sidebar();

      expect(screen.queryByRole('navigation', { name: 'Legal' })).not.toBeInTheDocument();
    });
  });

  describe('Reconnect X banner', () => {
    const NEEDS_RECONNECT = {
      handle: 'ada',
      charLimit: 280,
      needsReconnect: true,
      scheduledPostsWaiting: 2,
      photoUrl: null,
      offerPhoto: false,
    };

    it.each(['/new', '/posts', '/persona', '/settings'])(
      'says on %s that Scheduled posts wait for X to be reconnected',
      async (path) => {
        vi.mocked(xConnectionService.get).mockResolvedValue(NEEDS_RECONNECT);
        renderSignedIn(path);

        const banner = within(await screen.findByRole('region', { name: 'Reconnect X' }));
        expect(
          banner.getByText("X no longer accepts Pumpkit's access to @ada."),
        ).toBeInTheDocument();
        expect(
          banner.getByText(/Scheduled posts won't go out until you reconnect/),
        ).toBeInTheDocument();
      },
    );

    it('starts reconnecting from its button', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(NEEDS_RECONNECT);
      vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
        'https://x.com/i/oauth2/authorize?state=s',
      );
      renderSignedIn('/persona');

      const banner = within(await screen.findByRole('region', { name: 'Reconnect X' }));
      fireEvent.click(banner.getByRole('button', { name: 'Reconnect X' }));

      await waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
      );
    });

    it('stays away on an Instance without X, where reconnecting cannot work', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(NEEDS_RECONNECT);
      renderSignedIn('/new', { instance: { ...SELLS_PLANS, x_connection: false } });

      await waitFor(() =>
        expect(screen.getByRole('link', { name: /^Your account/ })).toHaveAccessibleName(/@ada/),
      );
      expect(screen.queryByRole('region', { name: 'Reconnect X' })).not.toBeInTheDocument();
    });

    it('stays away while X accepts the X connection', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...NEEDS_RECONNECT,
        needsReconnect: false,
      });
      renderSignedIn('/new');

      await waitFor(() =>
        expect(screen.getByRole('link', { name: /^Your account/ })).toHaveAccessibleName(/@ada/),
      );
      expect(screen.queryByRole('region', { name: 'Reconnect X' })).not.toBeInTheDocument();
    });
  });

  describe('New post', () => {
    it('sends /home to /new', async () => {
      renderSignedIn('/home');

      expect(
        await screen.findByRole('heading', { level: 1, name: 'New post' }),
      ).toBeInTheDocument();
      expect(currentPath()).toBe('/new');
    });

    it('opens an empty /new from a Post with the cursor in the Brief', async () => {
      await withPostOnScreen();

      fireEvent.click((await sidebar()).getByRole('link', { name: 'New post' }));

      expect(await screen.findByLabelText('Brief')).toBeInTheDocument();
      expect(currentPath()).toBe('/new');
      expect(screen.queryByRole('article', { name: 'Text' })).not.toBeInTheDocument();
      expect(screen.getByLabelText('Brief')).toHaveValue('');
      expect(screen.getByLabelText('Brief')).toHaveFocus();
      expect(track).toHaveBeenCalledWith('sidebar_new_post_clicked', { source: 'sidebar' });
    });

    it('opens an empty /new on the shortcut from another page', async () => {
      await withPostOnScreen();
      fireEvent.click((await sidebar()).getByRole('link', { name: 'Persona' }));
      await screen.findByRole('heading', { level: 1, name: 'Persona' });

      newPostShortcut();

      expect(
        await screen.findByRole('heading', { level: 1, name: 'New post' }),
      ).toBeInTheDocument();
      expect(currentPath()).toBe('/new');
      expect(screen.queryByRole('article', { name: 'Text' })).not.toBeInTheDocument();
      expect(screen.getByLabelText('Brief')).toHaveValue('');
      expect(track).toHaveBeenCalledWith('sidebar_new_post_clicked', { source: 'shortcut' });
    });

    it('clears a half-typed Brief on the shortcut, even while typing it', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderSignedIn('/new');
      const brief = await screen.findByLabelText('Brief');
      fireEvent.change(brief, { target: { value: 'half a thought' } });

      newPostShortcut(brief);

      expect(brief).toHaveValue('');
    });

    it('starts one New post when the shortcut is held down', async () => {
      renderSignedIn('/new');
      await sidebar();

      newPostShortcut();
      fireEvent.keyDown(window, { key: 'O', ctrlKey: true, shiftKey: true, repeat: true });

      expect(
        vi.mocked(track).mock.calls.filter(([event]) => event === 'sidebar_new_post_clicked'),
      ).toHaveLength(1);
    });

    it('leaves the Brief alone when the shortcut is pressed over a dialog', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderSignedIn('/new');
      const brief = await screen.findByLabelText('Brief');
      fireEvent.change(brief, { target: { value: 'half a thought' } });
      fireEvent.click(screen.getByRole('button', { name: 'Open sidebar' }));
      await screen.findByRole('dialog', { name: 'Sidebar' });

      newPostShortcut();

      expect(brief).toHaveValue('half a thought');
    });

    it('keeps the Brief while a Version is being written', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      vi.mocked(postService.start).mockReturnValue(new Promise(() => {}));
      renderSignedIn('/new');
      fireEvent.change(await screen.findByLabelText('Brief'), {
        target: { value: 'ship small things' },
      });
      fireEvent.click(await screen.findByRole('button', { name: 'Write the post' }));

      newPostShortcut();
      fireEvent.click((await sidebar()).getByRole('link', { name: 'New post' }));

      expect(screen.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(screen.getByText(/writing your post/i)).toBeInTheDocument();
    });
  });

  describe('On a phone', () => {
    it('opens the sidebar as a drawer from the header and closes it on a page change', async () => {
      renderSignedIn('/new');
      await sidebar();

      fireEvent.click(screen.getByRole('button', { name: 'Open sidebar' }));
      const drawer = within(await screen.findByRole('dialog', { name: 'Sidebar' }));
      fireEvent.click(drawer.getByRole('link', { name: /^Persona/ }));

      await waitFor(() =>
        expect(screen.queryByRole('dialog', { name: 'Sidebar' })).not.toBeInTheDocument(),
      );
      expect(currentPath()).toBe('/persona');
    });

    it('closes the drawer on Escape', async () => {
      renderSignedIn('/new');
      await sidebar();

      fireEvent.click(screen.getByRole('button', { name: 'Open sidebar' }));
      await screen.findByRole('dialog', { name: 'Sidebar' });
      fireEvent.keyDown(window, { key: 'Escape' });

      await waitFor(() =>
        expect(screen.queryByRole('dialog', { name: 'Sidebar' })).not.toBeInTheDocument(),
      );
    });
  });
});
