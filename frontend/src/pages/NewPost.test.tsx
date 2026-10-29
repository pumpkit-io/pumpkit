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

import type { Instance } from '@/lib/instance';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { postService, type PostDetail } from '@/services/postService';
import { xConnectionService } from '@/services/xConnectionService';
import {
  LEVELSIO,
  NOT_SUBSCRIBED,
  PAULG,
  SUBSCRIBED,
  apiError,
  renderSignedIn,
} from './testing/signedInApp';

function currentPath() {
  return screen.getByRole('status', { name: 'Current path' }).textContent;
}

function renderNewPost(state?: unknown, instance: Instance = SELLS_PLANS) {
  return renderSignedIn('/new', { state, instance });
}

async function writer() {
  return within(await screen.findByRole('region', { name: "What's this one about?" }));
}

function postWith(final: string): PostDetail {
  return {
    id: 'post_01',
    brief: 'ship small things',
    versions: [
      {
        id: 'version_attempt_01',
        number: 1,
        feedback: null,
        format: 'post',
        parts: [{ text: final, charCount: final.length, charLimit: 280 }],
        tells: [],
      },
    ],
    status: 'draft',
    scheduledPost: null,
  };
}

/** A Subscribed User with one Inspiration author, ready to write. */
async function readyToWrite() {
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
  vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
  renderNewPost();
  await screen.findByRole('link', { name: 'Persona: @levelsio' });
  const area = await writer();
  await area.findByRole('button', { name: 'Write the Post' });
  return area;
}

async function writeBrief(area: Awaited<ReturnType<typeof writer>>, brief: string) {
  fireEvent.change(area.getByLabelText('Brief'), { target: { value: brief } });
  fireEvent.click(area.getByRole('button', { name: 'Write the Post' }));
}

describe('New post', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([]);
    vi.mocked(inspirationAuthorService.add).mockReset();
    vi.mocked(inspirationAuthorService.remove).mockReset();
    vi.mocked(inspirationAuthorService.refresh).mockReset();
    vi.mocked(postService.start).mockReset();
    vi.mocked(postService.get).mockReset().mockResolvedValue(postWith('the final text'));
    vi.mocked(postService.addVersion).mockReset();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(track).mockClear();
  });

  it('shows one line above the composer, with no instructions or field labels', async () => {
    renderNewPost();

    expect(await screen.findByRole('heading', { level: 1, name: 'New post' })).toBeInTheDocument();
    const area = await writer();
    expect(area.getByRole('heading', { level: 2, name: "What's this one about?" })).toBeVisible();
    const brief = area.getByLabelText('Brief');
    expect(brief).toHaveAttribute('placeholder', 'Ramble here…');
    expect(brief).toHaveFocus();
    expect(area.getByRole('radiogroup', { name: 'Format' })).toBeInTheDocument();
    expect(area.queryByText('Brief')).not.toBeInTheDocument();
    expect(area.queryByText('Format')).not.toBeInTheDocument();
    expect(area.queryByText(/rambling is fine/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'How your posts sound' })).not.toBeInTheDocument();
  });

  describe('Persona chip', () => {
    it("lists the Inspiration authors' handles in the header and links to Persona", async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderNewPost();

      const chip = await screen.findByRole('link', { name: 'Persona: @levelsio, @paulg' });
      expect(chip).toHaveAttribute('href', '/persona');
      expect(chip.closest('header')).not.toBeNull();
    });

    it('asks to set up an empty Persona', async () => {
      renderNewPost();

      expect(
        await screen.findByRole('link', { name: 'Persona: empty, set it up' }),
      ).toHaveAttribute('href', '/persona');
    });
  });

  describe('Writing a Post', () => {
    it('replaces the write button with "Set up your Persona" while the Persona is empty', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderNewPost();

      const area = await writer();
      const setUp = await area.findByRole('link', { name: 'Set up your Persona' });
      expect(area.queryByText(/at least one Inspiration author/i)).not.toBeInTheDocument();
      expect(area.queryByRole('button', { name: 'Write the Post' })).not.toBeInTheDocument();

      fireEvent.click(setUp);

      expect(await screen.findByRole('heading', { level: 1, name: 'Persona' })).toBeInTheDocument();
    });

    it('replaces the write button with "Subscribe to write" for a User who is not Subscribed', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderNewPost();

      const area = await writer();
      const subscribe = await area.findByRole('link', { name: 'Subscribe to write' });
      expect(area.getByLabelText('Brief')).toBeEnabled();
      expect(area.queryByRole('button', { name: 'Write the Post' })).not.toBeInTheDocument();

      fireEvent.click(subscribe);

      expect(await screen.findByRole('region', { name: 'Choose a Plan' })).toBeInTheDocument();
      expect(currentPath()).toBe('/settings');
      expect(track).toHaveBeenCalledWith('billing_choose_plan_opened', {
        source: 'new_post_write',
      });
    });

    it('asks a User who is neither Subscribed nor set up to subscribe first', async () => {
      renderNewPost();

      const area = await writer();
      expect(await area.findByRole('link', { name: 'Subscribe to write' })).toBeInTheDocument();
      expect(area.queryByRole('link', { name: 'Set up your Persona' })).not.toBeInTheDocument();
    });

    it('greys out the send arrow until something is typed', async () => {
      const area = await readyToWrite();
      expect(area.getByRole('button', { name: 'Write the Post' })).toBeDisabled();

      fireEvent.change(area.getByLabelText('Brief'), { target: { value: '   ' } });
      expect(area.getByRole('button', { name: 'Write the Post' })).toBeDisabled();

      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'ship small things' } });
      expect(area.getByRole('button', { name: 'Write the Post' })).toBeEnabled();
    });

    it('shows the shortcut hint beside the arrow only once something is typed', async () => {
      const area = await readyToWrite();
      expect(area.queryByText(/↵ to write/)).not.toBeInTheDocument();

      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'ship small things' } });

      expect(area.getByText(/↵ to write/)).toBeVisible();
    });

    it.each([
      ['⌘Enter', { metaKey: true }],
      ['Ctrl+Enter', { ctrlKey: true }],
    ])('sends the Brief with %s', async (_, modifier) => {
      vi.mocked(postService.start).mockReturnValue(new Promise(() => {}));
      const area = await readyToWrite();
      const brief = area.getByLabelText('Brief');
      fireEvent.change(brief, { target: { value: 'ship small things' } });

      fireEvent.keyDown(brief, { key: 'Enter', ...modifier });

      expect(postService.start).toHaveBeenCalledWith('ship small things', 'post');
    });

    it('leaves Enter alone, so it adds a newline instead of sending', async () => {
      const area = await readyToWrite();
      const brief = area.getByLabelText('Brief');
      fireEvent.change(brief, { target: { value: 'ship small things' } });

      const enter = fireEvent.keyDown(brief, { key: 'Enter' });

      expect(enter).toBe(true);
      expect(postService.start).not.toHaveBeenCalled();
    });

    it("writes the first Version, locking the composer while it waits, then opens the Post's page", async () => {
      let answer: (post: PostDetail) => void = () => {};
      vi.mocked(postService.start).mockReturnValue(new Promise((resolve) => (answer = resolve)));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(area.getByLabelText('Brief')).toBeDisabled();
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(area.getByRole('button', { name: /writing/i })).toBeDisabled();
      expect(area.getByRole('radio', { name: 'Thread' })).toBeDisabled();
      expect(area.queryByText(/↵ to write/)).not.toBeInTheDocument();
      expect(area.getByRole('status')).toHaveTextContent(
        'Writing your Post. This takes a minute or two.',
      );
      expect(postService.start).toHaveBeenCalledWith('ship small things', 'post');
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'brief' });

      answer(postWith('the final text'));

      await waitFor(() =>
        expect(screen.getByRole('status', { name: 'Current path' })).toHaveTextContent(
          '/posts/post_01',
        ),
      );
      const card = within(await screen.findByRole('article', { name: 'Version 1' }));
      expect(card.getByText('the final text')).toBeInTheDocument();
      expect(postService.get).toHaveBeenCalledWith('post_01');
    });

    it('empties the form on New post, back to a single post', async () => {
      const area = await readyToWrite();
      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'half a thought' } });
      fireEvent.click(area.getByRole('radio', { name: 'Thread' }));

      fireEvent.click(
        within(screen.getAllByRole('navigation', { name: 'Main' })[0]!).getByRole('link', {
          name: 'New post',
        }),
      );

      const fresh = await writer();
      await waitFor(() => expect(fresh.getByLabelText('Brief')).toHaveValue(''));
      expect(fresh.getByLabelText('Brief')).toHaveFocus();
      expect(fresh.getByRole('radio', { name: 'Single post' })).toBeChecked();
    });

    it('starts on a single post and writes a Thread when the User picks Thread', async () => {
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      const area = await readyToWrite();
      const format = within(area.getByRole('radiogroup', { name: 'Format' }));
      expect(format.getByRole('radio', { name: 'Single post' })).toBeChecked();
      expect(format.getByRole('radio', { name: 'Thread' })).not.toBeChecked();

      fireEvent.click(format.getByRole('radio', { name: 'Thread' }));
      await writeBrief(area, 'ship small things');

      expect(postService.start).toHaveBeenCalledWith('ship small things', 'thread');
    });

    it('shows a failure, keeps the Brief and retries it as a new Post', async () => {
      vi.mocked(postService.start)
        .mockRejectedValueOnce(apiError(502, 'Writing the Post failed. Please try again.'))
        .mockResolvedValueOnce(postWith('the final text'));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      const alert = await area.findByRole('alert');
      expect(alert).toHaveTextContent('Writing the Post failed. Please try again.');
      expect(
        area.getByLabelText('Brief').compareDocumentPosition(alert) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'brief' });

      fireEvent.click(area.getByRole('button', { name: 'Try again' }));

      expect(await screen.findByRole('article', { name: 'Version 1' })).toBeInTheDocument();
      expect(postService.start).toHaveBeenCalledTimes(2);
      expect(postService.start).toHaveBeenNthCalledWith(2, 'ship small things', 'post');
    });

    it('says when the User can write again once they reach the hourly limit', async () => {
      vi.mocked(postService.start).mockRejectedValue(
        apiError(429, "You've made 30 attempts at a Version in the last hour.", {
          retry_at: new Date(2026, 9, 6, 15, 42).toISOString(),
        }),
      );
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(
        await area.findByText(
          "You've made 30 attempts at a Version in the last hour. You can write again at 3:42 PM.",
        ),
      ).toHaveAttribute('role', 'status');
      expect(area.queryByRole('alert')).not.toBeInTheDocument();
      expect(area.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
    });

    it.each([
      [403, 'This needs a Subscription. Subscribe to continue.'],
      [422, 'The Brief is too long.'],
      [429, "You've made 30 attempts at a Version in the last hour."],
    ])('does not count a refusal with a %i as a failed Version', async (status, detail) => {
      vi.mocked(postService.start).mockRejectedValue(apiError(status, detail));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      await waitFor(() => expect(postService.start).toHaveBeenCalled());
      await waitFor(() => expect(area.getByLabelText('Brief')).toBeEnabled());
      expect(track).not.toHaveBeenCalledWith('post_version_failed', expect.anything());
    });

    it('counts a failure without a response as a failed Version', async () => {
      vi.mocked(postService.start).mockRejectedValue(new Error('Network Error'));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(await area.findByRole('alert')).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'brief' });
    });

    it('shows a length counter only near the Brief limit, and refuses a Brief over it', async () => {
      const area = await readyToWrite();
      const brief = area.getByLabelText('Brief');

      fireEvent.change(brief, { target: { value: 'a'.repeat(1000) } });
      expect(area.queryByText(/200,000/)).not.toBeInTheDocument();

      fireEvent.change(brief, { target: { value: 'a'.repeat(195_000) } });
      expect(area.getByText('195,000 / 200,000 characters')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Write the Post' })).toBeEnabled();

      fireEvent.change(brief, { target: { value: 'a'.repeat(200_005) } });
      expect(area.getByText('5 characters over the 200,000 limit')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Write the Post' })).toBeDisabled();
    });

    it('counts an emoji in the Brief as one character, as the backend does', async () => {
      const area = await readyToWrite();

      fireEvent.change(area.getByLabelText('Brief'), {
        target: { value: 'a'.repeat(199_999) + '😀' },
      });

      expect(area.getByText('200,000 / 200,000 characters')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Write the Post' })).toBeEnabled();
    });
  });

  describe('On an Instance that sells no Plans', () => {
    const NO_PLANS: Instance = { ...SELLS_PLANS, sells_plans: false };

    it('lets a User without a Subscription write, with no prompt to subscribe', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderNewPost(undefined, NO_PLANS);

      const area = await writer();
      expect(await area.findByRole('button', { name: 'Write the Post' })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /subscribe/i })).not.toBeInTheDocument();
      expect(billingService.fetchBillingMe).not.toHaveBeenCalled();
    });
  });
});
