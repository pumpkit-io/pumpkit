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
    list: vi.fn().mockResolvedValue([]),
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
import type { Instance } from '@/lib/instance';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { postService, type PostDetail } from '@/services/postService';
import { xConnectionService } from '@/services/xConnectionService';
import { LEVELSIO, NOT_SUBSCRIBED, PAULG, SUBSCRIBED, renderSignedIn } from './testing/signedInApp';

const WITH_ANALYTICS: Instance = {
  ...SELLS_PLANS,
  analytics: {
    key: 'phc_test',
    host: 'https://eu.i.posthog.com',
    ui_host: 'https://eu.posthog.com',
  },
};

const POST: PostDetail = {
  id: 'post_01',
  brief: 'ship small things',
  versions: [
    {
      id: 'version_attempt_01',
      number: 1,
      feedback: null,
      format: 'post',
      parts: [{ text: 'the final text', charCount: 14, charLimit: 280 }],
      tells: [],
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
  await screen.findByRole('article', { name: 'Version 1' });
}

describe('The signed-in shell', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(billingService.fetchPlans)
      .mockReset()
      .mockResolvedValue({ plans: [], termsVersion: '2026-10-11' });
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([]);
    vi.mocked(postService.start).mockReset();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(track).mockClear();
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
      expect(nav.getByRole('link', { name: /^Persona/ })).toHaveAttribute('aria-current', 'page');
      expect(nav.getByRole('link', { name: 'New post' })).not.toHaveAttribute('aria-current');

      fireEvent.click(nav.getByRole('link', { name: 'Posts' }));

      expect(await screen.findByRole('heading', { level: 1, name: 'Posts' })).toBeInTheDocument();
      expect(nav.getByRole('link', { name: 'Posts' })).toHaveAttribute('aria-current', 'page');
    });

    it('counts the places taken in the Persona out of three', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderSignedIn('/new');

      const nav = await sidebar();
      expect(
        await nav.findByRole('link', { name: 'Persona, 2 of 3 Inspiration authors' }),
      ).toBeInTheDocument();
    });

    it('counts an empty Persona as 0/3', async () => {
      renderSignedIn('/new');

      const persona = (await sidebar()).getByRole('link', { name: /^Persona/ });
      await waitFor(() => expect(persona).toHaveTextContent('0/3'));
      expect(persona).toHaveAccessibleName('Persona, 0 of 3 Inspiration authors');
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
      });
      vi.mocked(xConnectionService.get).mockResolvedValue({
        handle: 'ada',
        charLimit: 280,
        needsReconnect: false,
        scheduledPostsWaiting: 0,
      });
      renderSignedIn('/new');

      const card = within(await screen.findByRole('group', { name: 'Your account' }));
      expect(await card.findByText('Ada Lovelace')).toBeInTheDocument();
      expect(await card.findByText('@ada')).toBeInTheDocument();
      expect(await card.findByText('Pumpkit Pro')).toBeInTheDocument();
    });

    it('says "No Subscription" in the user card of a User who is not Subscribed', async () => {
      renderSignedIn('/new');

      const card = within(await screen.findByRole('group', { name: 'Your account' }));
      expect(await card.findByText('No Subscription')).toBeInTheDocument();
    });

    it('shows no Plan in the user card on an Instance that sells no Plans', async () => {
      renderSignedIn('/new', { instance: { ...SELLS_PLANS, sells_plans: false } });

      const card = within(await screen.findByRole('group', { name: 'Your account' }));
      expect(await card.findByText('Ada Lovelace')).toBeInTheDocument();
      expect(card.queryByText('No Subscription')).not.toBeInTheDocument();
    });

    it('keeps the user menu in the user card', async () => {
      renderSignedIn('/new');

      fireEvent.keyDown(await screen.findByRole('button', { name: 'User menu' }), {
        key: 'Enter',
      });

      expect(await screen.findByRole('menuitem', { name: 'Account' })).toBeInTheDocument();
      expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeInTheDocument();
    });

    it('has no collapse toggle', async () => {
      renderSignedIn('/new');
      await sidebar();

      expect(screen.queryByRole('button', { name: 'Close sidebar' })).not.toBeInTheDocument();
      expect(screen.queryByRole('navigation', { name: 'Sidebar rail' })).not.toBeInTheDocument();
    });

    it('links to the Privacy Policy and the Terms at the bottom, in a new tab', async () => {
      renderSignedIn('/new', { instance: WITH_OPERATOR });
      await sidebar();

      const legal = within(screen.getByRole('navigation', { name: 'Legal' }));
      const privacy = legal.getByRole('link', { name: 'Privacy Policy' });
      const terms = legal.getByRole('link', { name: 'Terms' });
      expect(privacy).toHaveAttribute('href', '/privacy');
      expect(terms).toHaveAttribute('href', '/terms');
      for (const link of [privacy, terms]) expect(link).toHaveAttribute('target', '_blank');
    });

    it('offers Cookie settings next to the legal links', async () => {
      renderSignedIn('/new', {
        instance: { ...WITH_OPERATOR, analytics: WITH_ANALYTICS.analytics },
      });
      await sidebar();

      const legal = within(screen.getByRole('navigation', { name: 'Legal' }));
      expect(legal.getByRole('button', { name: 'Cookie settings' })).toBeInTheDocument();
    });

    it('offers only Cookie settings on an Instance with analytics but no Operator details', async () => {
      renderSignedIn('/new', { instance: WITH_ANALYTICS });
      await sidebar();

      expect(screen.getByRole('button', { name: 'Cookie settings' })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Privacy Policy' })).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Terms' })).not.toBeInTheDocument();
    });

    it('has no legal links or Cookie settings on an Instance with neither', async () => {
      renderSignedIn('/new');
      await sidebar();

      expect(screen.queryByRole('link', { name: 'Privacy Policy' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Cookie settings' })).not.toBeInTheDocument();
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
      expect(screen.queryByRole('article', { name: 'Version 1' })).not.toBeInTheDocument();
      expect(screen.getByLabelText('Brief')).toHaveValue('');
      expect(screen.getByLabelText('Brief')).toHaveFocus();
      expect(track).toHaveBeenCalledWith('sidebar_new_post_clicked', { source: 'sidebar' });
    });

    it('opens an empty /new on the shortcut from another page', async () => {
      await withPostOnScreen();
      fireEvent.click((await sidebar()).getByRole('link', { name: /^Persona/ }));
      await screen.findByRole('heading', { level: 1, name: 'Persona' });

      newPostShortcut();

      expect(
        await screen.findByRole('heading', { level: 1, name: 'New post' }),
      ).toBeInTheDocument();
      expect(currentPath()).toBe('/new');
      expect(screen.queryByRole('article', { name: 'Version 1' })).not.toBeInTheDocument();
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
      fireEvent.click(await screen.findByRole('button', { name: 'Subscribe to write' }));
      await screen.findByRole('dialog');

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
      fireEvent.click(await screen.findByRole('button', { name: 'Write the Post' }));

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
