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

import type { Instance } from '@/lib/instance';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { postService, type Part, type Post, type Tell, type Version } from '@/services/postService';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import {
  LEVELSIO,
  NOT_SUBSCRIBED,
  PAULG,
  SUBSCRIBED,
  apiError,
  renderSignedIn,
} from './testing/signedInApp';

function renderNewPost(state?: unknown, instance: Instance = SELLS_PLANS) {
  return renderSignedIn('/new', { state, instance });
}

async function writer() {
  return within(await screen.findByRole('region', { name: 'Write a Post' }));
}

function postWith(final: string, finalCharCount = final.length, tells: Tell[] = []): Post {
  return {
    id: 'post_01',
    brief: 'ship small things',
    versions: [
      {
        id: 'version_attempt_01',
        number: 1,
        feedback: null,
        format: 'post',
        parts: [{ text: final, charCount: finalCharCount, charLimit: 280 }],
        tells,
      },
    ],
  };
}

function threadWith(parts: Part[]): Post {
  return {
    id: 'post_01',
    brief: 'ship small things',
    versions: [
      {
        id: 'version_attempt_01',
        number: 1,
        feedback: null,
        format: 'thread',
        parts,
        tells: [],
      },
    ],
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
    vi.mocked(postService.addVersion).mockReset();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(track).mockClear();
  });

  it('shows the Brief box and the Format under the "New post" header', async () => {
    renderNewPost();

    expect(await screen.findByRole('heading', { level: 1, name: 'New post' })).toBeInTheDocument();
    const area = await writer();
    expect(area.getByLabelText('Brief')).toBeInTheDocument();
    expect(area.getByRole('radiogroup', { name: 'Format' })).toBeInTheDocument();
    expect(area.getByText(/rambling is fine/i)).toBeInTheDocument();
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
      expect(area.getByText(/at least one Inspiration author/i)).toBeInTheDocument();
      expect(area.queryByRole('button', { name: 'Write the Post' })).not.toBeInTheDocument();

      fireEvent.click(setUp);

      expect(await screen.findByRole('heading', { level: 1, name: 'Persona' })).toBeInTheDocument();
    });

    it('replaces the write button with "Subscribe to write" for a User who is not Subscribed', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderNewPost();

      const area = await writer();
      const subscribe = await area.findByRole('button', { name: 'Subscribe to write' });
      expect(area.getByText('Your Drafts, schedule and Persona are kept.')).toBeInTheDocument();
      expect(area.queryByRole('button', { name: 'Write the Post' })).not.toBeInTheDocument();

      fireEvent.click(subscribe);

      expect(await screen.findByRole('dialog', { name: 'Billing' })).toBeInTheDocument();
    });

    it('asks a User who is neither Subscribed nor set up to subscribe first', async () => {
      renderNewPost();

      const area = await writer();
      expect(await area.findByRole('button', { name: 'Subscribe to write' })).toBeInTheDocument();
      expect(area.queryByRole('link', { name: 'Set up your Persona' })).not.toBeInTheDocument();
    });

    it('writes the first Version, disabling the Brief while it waits, then shows only the Final', async () => {
      let answer: (post: Post) => void = () => {};
      vi.mocked(postService.start).mockReturnValue(new Promise((resolve) => (answer = resolve)));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(area.getByLabelText('Brief')).toBeDisabled();
      expect(area.getByRole('button', { name: /writing/i })).toBeDisabled();
      expect(area.getByRole('status')).toHaveTextContent(/writing your post/i);
      expect(postService.start).toHaveBeenCalledWith('ship small things', 'post');
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'brief' });

      answer(postWith('the final text'));

      const final = within(await area.findByRole('article', { name: 'Final' }));
      expect(final.getByText('the final text')).toBeInTheDocument();
      expect(final.getByText('14 / 280 characters')).toBeInTheDocument();
      expect(final.queryByText(/characters over/i)).not.toBeInTheDocument();
      expect(area.getAllByRole('article')).toHaveLength(1);
      expect(area.queryByText(/written first/i)).not.toBeInTheDocument();
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

    it('starts a New Post on a single post again', async () => {
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      const area = await readyToWrite();
      fireEvent.click(area.getByRole('radio', { name: 'Thread' }));
      await writeBrief(area, 'ship small things');
      await area.findByText('the final text');

      fireEvent.click(area.getByRole('button', { name: 'New Post' }));

      expect(area.getByRole('radio', { name: 'Single post' })).toBeChecked();
    });

    it('shows a Thread as its Parts in order, each with its own counter and copy', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
      vi.mocked(postService.start).mockResolvedValue(
        threadWith([
          { text: 'the first part', charCount: 14, charLimit: 280 },
          { text: 'the second part', charCount: 290, charLimit: 280 },
        ]),
      );
      const area = await readyToWrite();
      fireEvent.click(area.getByRole('radio', { name: 'Thread' }));
      await writeBrief(area, 'ship small things');

      const final = within(await area.findByRole('article', { name: 'Final' }));
      const parts = final.getAllByRole('listitem', { name: /^Part \d$/ });
      expect(parts.map((part) => part.getAttribute('aria-label'))).toEqual(['Part 1', 'Part 2']);
      const [first, second] = parts.map((part) => within(part));
      expect(first.getByText('the first part')).toBeInTheDocument();
      expect(first.getByText('14 / 280 characters')).toBeInTheDocument();
      expect(second.getByText('290 / 280 characters')).toBeInTheDocument();
      expect(second.getByText("10 characters over X's 280-character limit")).toBeInTheDocument();

      fireEvent.click(second.getByRole('button', { name: 'Copy Part 2' }));

      expect(writeText).toHaveBeenCalledWith('the second part');
      expect(await second.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('post_part_copied');
    });

    it('shows a single post with no Part copy buttons', async () => {
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      const area = await readyToWrite();
      await writeBrief(area, 'ship');

      const final = within(await area.findByRole('article', { name: 'Final' }));
      expect(final.queryByRole('button', { name: /Copy Part/ })).not.toBeInTheDocument();
      expect(final.queryByRole('listitem', { name: /^Part/ })).not.toBeInTheDocument();
    });

    it("flags a Final over the X account's limit", async () => {
      vi.mocked(postService.start).mockResolvedValue(postWith('x'.repeat(292)));
      const area = await readyToWrite();

      await writeBrief(area, 'ship');

      const final = within(await area.findByRole('article', { name: 'Final' }));
      expect(final.getByText('292 / 280 characters')).toBeInTheDocument();
      expect(final.getByText("12 characters over X's 280-character limit")).toBeInTheDocument();
    });

    it('lists the tells the slop check found next to the Final', async () => {
      vi.mocked(postService.start).mockResolvedValue(
        postWith('the unfair advantage — distribution', undefined, [
          { name: 'em_dash', description: 'em dash' },
          { name: 'startup_cliche', description: 'startup-commentary cliche' },
        ]),
      );
      const area = await readyToWrite();

      await writeBrief(area, 'ship');

      const final = within(await area.findByRole('article', { name: 'Final' }));
      const tells = within(final.getByRole('list', { name: 'Machine-written tells' }));
      expect(tells.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        'em dash',
        'startup-commentary cliche',
      ]);
    });

    it('says the slop check found no tells when there are none', async () => {
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      const area = await readyToWrite();

      await writeBrief(area, 'ship');

      const final = within(await area.findByRole('article', { name: 'Final' }));
      expect(final.getByText('No machine-written tells found.')).toBeInTheDocument();
      expect(final.queryByRole('list', { name: 'Machine-written tells' })).not.toBeInTheDocument();
    });

    it('copies the Final', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      const area = await readyToWrite();
      await writeBrief(area, 'ship');

      fireEvent.click(await area.findByRole('button', { name: 'Copy Final' }));

      expect(writeText).toHaveBeenCalledWith('the final text');
      expect(await area.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('post_final_copied');
    });

    it('shows a failure, keeps the Brief and retries it as a new Post', async () => {
      vi.mocked(postService.start)
        .mockRejectedValueOnce(apiError(502, 'Writing the Post failed. Please try again.'))
        .mockResolvedValueOnce(postWith('the final text'));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(await area.findByRole('alert')).toHaveTextContent(
        'Writing the Post failed. Please try again.',
      );
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'brief' });

      fireEvent.click(area.getByRole('button', { name: 'Try again' }));

      expect(await area.findByText('the final text')).toBeInTheDocument();
      expect(postService.start).toHaveBeenCalledTimes(2);
      expect(postService.start).toHaveBeenNthCalledWith(2, 'ship small things', 'post');
      expect(area.queryByRole('alert')).not.toBeInTheDocument();
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

    it('clears the screen on "New Post"', async () => {
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      const area = await readyToWrite();
      await writeBrief(area, 'ship small things');
      await area.findByText('the final text');

      fireEvent.click(area.getByRole('button', { name: 'New Post' }));

      expect(area.queryByText('the final text')).not.toBeInTheDocument();
      expect(area.getByLabelText('Brief')).toHaveValue('');
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

  describe('Sending a Final to X', () => {
    const CONNECTED: XConnection = {
      handle: 'ada',
      charLimit: 280,
      needsReconnect: false,
      scheduledPostsWaiting: 0,
    };
    // The tests run in Europe/Rome (vitest.config.ts), two hours ahead of UTC in October.
    const SCHEDULED: ScheduledPost = {
      id: 'scheduled_post_01',
      parts: [{ text: 'the final text', live: false, xPostUrl: null }],
      state: 'scheduled',
      publishAt: '2026-10-12T07:00:00Z',
      publishedAt: null,
      xPostUrl: null,
      failedReason: null,
      community: null,
      shareWithFollowers: false,
      createdAt: '2026-10-10T12:00:00Z',
    };

    afterEach(() => {
      vi.useRealTimers();
    });

    beforeEach(() => {
      // The fixtures' times are in October 2026, so the picker's min would block them once they passed.
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(new Date('2026-10-10T12:00'));
      vi.mocked(scheduledPostService.schedule).mockReset();
      vi.mocked(scheduledPostService.postNow).mockReset();
      vi.mocked(xConnectionService.startAuthorization).mockReset();
      vi.mocked(redirectTo).mockReset();
    });

    async function finalWritten(final = 'the final text') {
      vi.mocked(postService.start).mockResolvedValue(postWith(final));
      const area = await readyToWrite();
      await writeBrief(area, 'ship');
      return within(await area.findByRole('article', { name: 'Final' }));
    }

    it("schedules the Final for a time in the User's timezone, recording its Version", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.schedule).mockResolvedValue(SCHEDULED);
      const final = await finalWritten();

      fireEvent.click(final.getByRole('button', { name: 'Schedule' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Schedule this Final' }));
      expect(dialog.getByText('the final text')).toBeInTheDocument();
      expect(dialog.getByText('14 / 280')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Schedule' })).toBeDisabled();
      fireEvent.change(dialog.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(dialog.getByRole('button', { name: 'Schedule' }));

      expect(await dialog.findByText(/scheduled for oct 12, 2026, 9:00/i)).toBeInTheDocument();
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        '2026-10-12T07:00:00.000Z',
        { community: null, shareWithFollowers: false },
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'post',
        part_count: 1,
        source: 'final',
        post_now: false,
        destination: 'profile',
      });
      expect(dialog.getByRole('link', { name: 'See Scheduled posts' })).toHaveAttribute(
        'href',
        '/scheduled',
      );
    });

    it('shows why scheduling was refused and keeps the dialog open', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.schedule).mockRejectedValue(
        apiError(422, 'Pick a time at least a minute from now.'),
      );
      const final = await finalWritten();

      fireEvent.click(final.getByRole('button', { name: 'Schedule' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Schedule this Final' }));
      fireEvent.change(dialog.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(dialog.getByRole('button', { name: 'Schedule' }));

      expect(
        await dialog.findByText('Pick a time at least a minute from now.'),
      ).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Schedule' })).toBeEnabled();
    });

    it('posts the Final now after a confirmation and links to it on X', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...SCHEDULED,
        state: 'published',
        publishedAt: '2026-10-10T12:00:14Z',
        xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
      });
      const final = await finalWritten();

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      expect(dialog.getByText(/goes out on @ada straight away/i)).toBeInTheDocument();
      expect(scheduledPostService.postNow).not.toHaveBeenCalled();
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      expect(await dialog.findByText('Published on X.')).toBeInTheDocument();
      expect(dialog.getByRole('link', { name: 'View on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1890000000000000001',
      );
      expect(scheduledPostService.postNow).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        { community: null, shareWithFollowers: false },
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'post',
        part_count: 1,
        source: 'final',
        post_now: true,
        destination: 'profile',
      });
    });

    it('shows the reason when posting the Final now Failed', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...SCHEDULED,
        state: 'failed',
        failedReason: 'X refused the post: duplicate content.',
      });
      const final = await finalWritten();

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      expect(await dialog.findByText('X refused the post: duplicate content.')).toBeInTheDocument();
      expect(dialog.getByText('This Scheduled post Failed.')).toBeInTheDocument();
      expect(dialog.queryByText(/sent to x/i)).not.toBeInTheDocument();
      expect(dialog.queryByRole('link', { name: 'View on X' })).not.toBeInTheDocument();
    });

    it('says Pumpkit will retry when X was busy for a Final posted now', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.postNow).mockResolvedValue(SCHEDULED);
      const final = await finalWritten();

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      expect(
        await dialog.findByText('X was busy. Pumpkit will keep trying for the next 15 minutes.'),
      ).toBeInTheDocument();
      expect(dialog.getByRole('link', { name: 'See Scheduled posts' })).toBeInTheDocument();
    });

    it("refuses a Final over X's limit by X's count", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      const final = await finalWritten('a'.repeat(290));

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      expect(dialog.getByText('10 characters over the 280 limit')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Post now' })).toBeDisabled();
    });

    async function threadFinalWritten(parts: string[]) {
      vi.mocked(postService.start).mockResolvedValue(
        threadWith(parts.map((text) => ({ text, charCount: text.length, charLimit: 280 }))),
      );
      const area = await readyToWrite();
      fireEvent.click(area.getByRole('radio', { name: 'Thread' }));
      await writeBrief(area, 'ship');
      return within(await area.findByRole('article', { name: 'Final' }));
    }

    it("previews every Part of a Thread's Final with its counter before scheduling it", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.schedule).mockResolvedValue({
        ...SCHEDULED,
        parts: [
          { text: 'the first part', live: false, xPostUrl: null },
          { text: 'the second part', live: false, xPostUrl: null },
        ],
      });
      const final = await threadFinalWritten(['the first part', 'the second part']);

      fireEvent.click(final.getByRole('button', { name: 'Schedule' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Schedule this Final' }));
      const parts = within(dialog.getByRole('list', { name: 'Parts' }))
        .getAllByRole('listitem')
        .map((part) => within(part));
      expect(parts).toHaveLength(2);
      expect(parts[0].getByText('Part 1')).toBeInTheDocument();
      expect(parts[0].getByText('the first part')).toBeInTheDocument();
      expect(parts[0].getByText('14 / 280')).toBeInTheDocument();
      expect(parts[1].getByText('Part 2')).toBeInTheDocument();
      expect(parts[1].getByText('the second part')).toBeInTheDocument();
      expect(parts[1].getByText('15 / 280')).toBeInTheDocument();
      fireEvent.change(dialog.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(dialog.getByRole('button', { name: 'Schedule' }));

      expect(await dialog.findByText(/scheduled for oct 12, 2026, 9:00/i)).toBeInTheDocument();
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        '2026-10-12T07:00:00.000Z',
        { community: null, shareWithFollowers: false },
      );
    });

    it("keeps Post now disabled while any Part of a Thread's Final is over X's limit", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      const final = await threadFinalWritten(['the first part', 'a'.repeat(290), 'the last part']);

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      const parts = within(dialog.getByRole('list', { name: 'Parts' }))
        .getAllByRole('listitem')
        .map((part) => within(part));
      expect(parts[0].getByText('14 / 280')).toBeInTheDocument();
      expect(parts[1].getByText('10 characters over the 280 limit')).toBeInTheDocument();
      expect(parts[2].getByText('13 / 280')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Post now' })).toBeDisabled();
    });

    it('lets a Final over 280 go to an X Premium account', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, charLimit: 25_000 });
      const final = await finalWritten('a'.repeat(290));

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      expect(dialog.getByText('290 / 25,000')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Post now' })).toBeEnabled();
    });

    it.each(['Schedule', 'Post now'])(
      'sends the User to connect X first when %s is pressed without an X connection',
      async (action) => {
        vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
          'https://x.com/i/oauth2/authorize?state=s',
        );
        const final = await finalWritten();

        fireEvent.click(final.getByRole('button', { name: action }));

        const dialog = within(await screen.findByRole('dialog'));
        expect(dialog.getByText('Connect your X account to post this Final.')).toBeInTheDocument();
        expect(dialog.queryByLabelText('Date and time')).not.toBeInTheDocument();
        fireEvent.click(dialog.getByRole('button', { name: 'Connect X' }));
        await waitFor(() =>
          expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
        );
        expect(scheduledPostService.schedule).not.toHaveBeenCalled();
        expect(scheduledPostService.postNow).not.toHaveBeenCalled();
      },
    );

    it('asks the User to reconnect X when X no longer accepts its access', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, needsReconnect: true });
      const final = await finalWritten();

      fireEvent.click(final.getByRole('button', { name: 'Schedule' }));

      const dialog = within(await screen.findByRole('dialog'));
      expect(dialog.getByText('Reconnect X to post this Final.')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Reconnect X' })).toBeInTheDocument();
    });

    describe('into a Community', () => {
      const COMMUNITY_ID = '1493446837214187523';
      const COMMUNITY_URL = `https://x.com/i/communities/${COMMUNITY_ID}`;

      beforeEach(() => {
        // As when the Instance has no twitterapi.io: the Community comes back without a name.
        vi.mocked(scheduledPostService.lookUpCommunity)
          .mockReset()
          .mockImplementation(async (id) => ({
            id,
            name: null,
            url: `https://x.com/i/communities/${id}`,
          }));
      });

      it('offers My profile first, and the followers checkbox only while a Community is chosen', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
        const final = await finalWritten();

        fireEvent.click(final.getByRole('button', { name: 'Post now' }));

        const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
        expect(dialog.getByLabelText('Post to')).toHaveDisplayValue('My profile');
        expect(dialog.queryByLabelText('Also share with followers')).not.toBeInTheDocument();
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'community' } });
        expect(dialog.getByLabelText('Also share with followers')).toBeChecked();
        expect(dialog.getByRole('button', { name: 'Post now' })).toBeDisabled();
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'profile' } });
        expect(dialog.queryByLabelText('Also share with followers')).not.toBeInTheDocument();
      });

      it('posts the Final now into a pasted Community, shared with followers by default', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
        vi.mocked(scheduledPostService.postNow).mockResolvedValue({
          ...SCHEDULED,
          state: 'published',
          publishedAt: '2026-10-10T12:00:14Z',
          xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
          community: { id: COMMUNITY_ID, name: null, url: COMMUNITY_URL },
          shareWithFollowers: true,
        });
        const final = await finalWritten();

        fireEvent.click(final.getByRole('button', { name: 'Post now' }));
        const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'community' } });
        fireEvent.change(dialog.getByLabelText('Community URL or ID'), {
          target: { value: COMMUNITY_URL },
        });
        await vi.waitFor(() =>
          expect(dialog.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
        );
        expect(
          dialog.getByText(/goes out from @ada into the Community straight away/i),
        ).toBeInTheDocument();
        fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

        expect(await dialog.findByText('Published on X.')).toBeInTheDocument();
        expect(scheduledPostService.postNow).toHaveBeenCalledWith(
          { sourceVersionId: 'version_attempt_01' },
          { community: { id: COMMUNITY_ID, name: null }, shareWithFollowers: true },
        );
        expect(track).toHaveBeenCalledWith('scheduled_post_created', {
          format: 'post',
          part_count: 1,
          source: 'final',
          post_now: true,
          destination: 'community',
          share_with_followers: true,
        });
      });

      it('says a Final goes into a Community picked from the past ones', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
        vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([
          { id: COMMUNITY_ID, name: 'Indie makers', url: COMMUNITY_URL },
        ]);
        const final = await finalWritten();

        fireEvent.click(final.getByRole('button', { name: 'Post now' }));
        const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
        const option = await dialog.findByRole<HTMLOptionElement>('option', {
          name: 'Indie makers',
        });
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: option.value } });

        expect(
          dialog.getByText(/goes out from @ada into the Community straight away/i),
        ).toBeInTheDocument();
        vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([]);
      });

      it('schedules the Final into a Community kept from the followers', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
        vi.mocked(scheduledPostService.schedule).mockResolvedValue({
          ...SCHEDULED,
          community: { id: '123', name: null, url: 'https://x.com/i/communities/123' },
        });
        const final = await finalWritten();

        fireEvent.click(final.getByRole('button', { name: 'Schedule' }));
        const dialog = within(await screen.findByRole('dialog', { name: 'Schedule this Final' }));
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'community' } });
        fireEvent.change(dialog.getByLabelText('Community URL or ID'), {
          target: { value: '123' },
        });
        await vi.waitFor(() =>
          expect(dialog.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
        );
        fireEvent.click(dialog.getByLabelText('Also share with followers'));
        fireEvent.change(dialog.getByLabelText('Date and time'), {
          target: { value: '2026-10-12T09:00' },
        });
        expect(
          dialog.getByText(/goes out from @ada into the Community at the time you pick/i),
        ).toBeInTheDocument();
        fireEvent.click(dialog.getByRole('button', { name: 'Schedule' }));

        expect(await dialog.findByText(/scheduled for oct 12, 2026, 9:00/i)).toBeInTheDocument();
        expect(scheduledPostService.schedule).toHaveBeenCalledWith(
          { sourceVersionId: 'version_attempt_01' },
          '2026-10-12T07:00:00.000Z',
          { community: { id: '123', name: null }, shareWithFollowers: false },
        );
        expect(track).toHaveBeenCalledWith('scheduled_post_created', {
          format: 'post',
          part_count: 1,
          source: 'final',
          post_now: false,
          destination: 'community',
          share_with_followers: false,
        });
      });
    });

    it('points a User who is no longer Subscribed to Billing', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.postNow).mockRejectedValue(apiError(403, 'Subscribe first.'));
      const final = await finalWritten();
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));
      const confirm = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      fireEvent.click(confirm.getByRole('button', { name: 'Post now' }));

      expect(await screen.findByRole('dialog', { name: 'Billing' })).toBeInTheDocument();
      fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

      fireEvent.click(final.getByRole('button', { name: 'Schedule' }));

      expect(await screen.findByRole('dialog', { name: 'Billing' })).toBeInTheDocument();
      expect(screen.queryByRole('dialog', { name: 'Schedule this Final' })).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('billing_dialog_opened', { source: 'final_schedule' });
    });
  });

  describe('Feedback', () => {
    const versionTwo: Version = {
      id: 'version_attempt_02',
      number: 2,
      feedback: 'make it shorter',
      format: 'post',
      parts: [{ text: 'the second final', charCount: 16, charLimit: 280 }],
      tells: [],
    };

    /** A Subscribed User looking at the first Version of a Post, with the Feedback box. */
    async function onFirstVersion() {
      vi.mocked(postService.start).mockResolvedValue(postWith('the first final'));
      const area = await readyToWrite();
      await writeBrief(area, 'ship small things');
      await area.findByText('the first final');
      return area;
    }

    function sendFeedback(area: Awaited<ReturnType<typeof writer>>, feedback: string) {
      fireEvent.change(area.getByLabelText('Feedback'), { target: { value: feedback } });
      fireEvent.click(area.getByRole('button', { name: 'Send Feedback' }));
    }

    it('adds a Version below the first, disabling the box while it waits, then clears it', async () => {
      let answer: (version: typeof versionTwo) => void = () => {};
      vi.mocked(postService.addVersion).mockReturnValue(
        new Promise((resolve) => (answer = resolve)),
      );
      const area = await onFirstVersion();

      sendFeedback(area, '  make it shorter ');

      expect(area.getByLabelText('Feedback')).toBeDisabled();
      expect(area.getByRole('button', { name: /writing/i })).toBeDisabled();
      expect(area.getByRole('status')).toHaveTextContent(/writing the next version/i);
      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'make it shorter', 'post');
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'feedback' });

      answer(versionTwo);

      const latest = within(await area.findByRole('region', { name: 'Version 2' }));
      expect(latest.getByText('the second final')).toBeInTheDocument();
      expect(latest.getByText('make it shorter')).toBeInTheDocument();
      expect(area.getByLabelText('Feedback')).toHaveValue('');
      expect(area.getByLabelText('Feedback')).toBeEnabled();
    });

    it("starts the Format on the latest Version's and sends the one the User picks", async () => {
      vi.mocked(postService.addVersion).mockResolvedValue({
        ...versionTwo,
        format: 'thread',
        parts: [
          { text: 'part one', charCount: 8, charLimit: 280 },
          { text: 'part two', charCount: 8, charLimit: 280 },
        ],
      });
      const area = await onFirstVersion();
      const format = () => within(area.getByRole('radiogroup', { name: 'Format' }));
      expect(format().getByRole('radio', { name: 'Single post' })).toBeChecked();

      fireEvent.click(format().getByRole('radio', { name: 'Thread' }));
      sendFeedback(area, 'expand it');

      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'expand it', 'thread');
      await area.findByRole('region', { name: 'Version 2' });
      expect(format().getByRole('radio', { name: 'Thread' })).toBeChecked();
    });

    it('shows each Version as a Thread with its Part count, or as nothing for a single post', async () => {
      vi.mocked(postService.addVersion).mockResolvedValue({
        ...versionTwo,
        format: 'thread',
        parts: [
          { text: 'part one', charCount: 8, charLimit: 280 },
          { text: 'part two', charCount: 8, charLimit: 280 },
          { text: 'part three', charCount: 10, charLimit: 280 },
        ],
      });
      const area = await onFirstVersion();
      sendFeedback(area, 'expand it');

      const threadVersion = within(await area.findByRole('region', { name: 'Version 2' }));
      expect(threadVersion.getByText('Thread, 3 Parts')).toBeInTheDocument();
      const postVersion = within(area.getByRole('region', { name: 'Version 1' }));
      expect(postVersion.queryByText(/Thread, /)).not.toBeInTheDocument();
    });

    it('starts the Format on Thread when the latest Version is a Thread', async () => {
      vi.mocked(postService.start).mockResolvedValue(
        threadWith([
          { text: 'the first part', charCount: 14, charLimit: 280 },
          { text: 'the second part', charCount: 15, charLimit: 280 },
        ]),
      );
      const area = await readyToWrite();
      fireEvent.click(area.getByRole('radio', { name: 'Thread' }));
      await writeBrief(area, 'ship small things');
      await area.findByRole('article', { name: 'Final' });

      const format = within(area.getByRole('radiogroup', { name: 'Format' }));
      expect(format.getByRole('radio', { name: 'Thread' })).toBeChecked();
    });

    it('keeps earlier Versions above the latest, read-only, each with its Feedback and copy', async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
      vi.mocked(postService.addVersion)
        .mockResolvedValueOnce(versionTwo)
        .mockResolvedValueOnce({
          ...versionTwo,
          id: 'version_attempt_03',
          number: 3,
          feedback: 'warmer',
          parts: [{ text: 'the third final', charCount: 15, charLimit: 280 }],
        });
      const area = await onFirstVersion();
      sendFeedback(area, 'make it shorter');
      await area.findByRole('region', { name: 'Version 2' });
      sendFeedback(area, 'warmer');
      await area.findByRole('region', { name: 'Version 3' });

      const [first, second, third] = area.getAllByRole('region', { name: /^Version \d$/ });
      expect(first).toHaveAccessibleName('Version 1');
      expect(second).toHaveAccessibleName('Version 2');
      expect(third).toHaveAccessibleName('Version 3');
      expect(within(second!).getByText('make it shorter')).toBeInTheDocument();
      expect(within(second!).getByText('the second final')).toBeInTheDocument();
      expect(within(second!).queryByRole('textbox')).not.toBeInTheDocument();
      expect(within(first!).queryByRole('textbox')).not.toBeInTheDocument();
      expect(area.getAllByLabelText('Feedback')).toHaveLength(1);
      expect(
        third!.compareDocumentPosition(area.getByLabelText('Feedback')) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();

      fireEvent.click(within(first!).getByRole('button', { name: 'Copy Final' }));
      expect(writeText).toHaveBeenCalledWith('the first final');
    });

    it('shows a failure and keeps the Feedback so it can be sent again', async () => {
      vi.mocked(postService.addVersion)
        .mockRejectedValueOnce(apiError(502, 'Writing the Post failed. Please try again.'))
        .mockResolvedValueOnce(versionTwo);
      const area = await onFirstVersion();

      sendFeedback(area, 'make it shorter');

      expect(await area.findByRole('alert')).toHaveTextContent(
        'Writing the Post failed. Please try again.',
      );
      expect(area.getByLabelText('Feedback')).toHaveValue('make it shorter');
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'feedback' });
      expect(area.queryByRole('region', { name: 'Version 2' })).not.toBeInTheDocument();

      fireEvent.click(area.getByRole('button', { name: 'Send Feedback' }));

      expect(await area.findByRole('region', { name: 'Version 2' })).toBeInTheDocument();
      expect(area.queryByRole('alert')).not.toBeInTheDocument();
      expect(area.getByLabelText('Feedback')).toHaveValue('');
    });

    it.each([
      [404, 'Post not found.'],
      [409, 'This Post has no Version to give Feedback on.'],
    ])('does not count a refusal with a %i as a failed Version', async (status, detail) => {
      vi.mocked(postService.addVersion).mockRejectedValue(apiError(status, detail));
      const area = await onFirstVersion();

      sendFeedback(area, 'make it shorter');

      expect(await area.findByRole('alert')).toHaveTextContent(detail);
      expect(track).not.toHaveBeenCalledWith('post_version_failed', expect.anything());
    });

    it('says when the User can send Feedback again once they reach the hourly limit', async () => {
      vi.mocked(postService.addVersion).mockRejectedValue(
        apiError(429, "You've made 30 attempts at a Version in the last hour.", {
          retry_at: new Date(2026, 9, 6, 15, 42).toISOString(),
        }),
      );
      const area = await onFirstVersion();

      sendFeedback(area, 'make it shorter');

      expect(
        await area.findByText(
          "You've made 30 attempts at a Version in the last hour. You can write again at 3:42 PM.",
        ),
      ).toHaveAttribute('role', 'status');
      expect(area.queryByRole('alert')).not.toBeInTheDocument();
      expect(area.getByLabelText('Feedback')).toHaveValue('make it shorter');
    });

    it('shows a length counter only near the Feedback limit, and refuses Feedback over it', async () => {
      const area = await onFirstVersion();
      const feedback = area.getByLabelText('Feedback');

      fireEvent.change(feedback, { target: { value: 'a'.repeat(1000) } });
      expect(area.queryByText(/100,000/)).not.toBeInTheDocument();

      fireEvent.change(feedback, { target: { value: 'a'.repeat(95_000) } });
      expect(area.getByText('95,000 / 100,000 characters')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Send Feedback' })).toBeEnabled();

      fireEvent.change(feedback, { target: { value: 'a'.repeat(100_003) } });
      expect(area.getByText('3 characters over the 100,000 limit')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Send Feedback' })).toBeDisabled();
    });

    it('counts an emoji in the Feedback as one character, as the backend does', async () => {
      const area = await onFirstVersion();

      fireEvent.change(area.getByLabelText('Feedback'), {
        target: { value: '😀'.repeat(95_000) },
      });

      expect(area.getByText('95,000 / 100,000 characters')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Send Feedback' })).toBeEnabled();
    });
  });

  it('opens the billing dialog after a successful checkout', async () => {
    renderNewPost({ checkoutStatus: 'success' });
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Billing')).toBeInTheDocument();
  });

  describe('On an Instance that sells no Plans', () => {
    const NO_PLANS: Instance = { ...SELLS_PLANS, sells_plans: false };

    it('lets a User without a Subscription write, with no prompt to subscribe', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderNewPost(undefined, NO_PLANS);

      const area = await writer();
      expect(await area.findByRole('button', { name: 'Write the Post' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /subscribe/i })).not.toBeInTheDocument();
      expect(billingService.fetchBillingMe).not.toHaveBeenCalled();
    });

    it('opens Schedule on a Final instead of Billing', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      renderNewPost(undefined, NO_PLANS);
      const area = await writer();
      await writeBrief(area, 'ship');
      const final = within(await area.findByRole('article', { name: 'Final' }));

      fireEvent.click(final.getByRole('button', { name: 'Schedule' }));

      expect(
        await screen.findByRole('dialog', { name: 'Schedule this Final' }),
      ).toBeInTheDocument();
      expect(screen.queryByRole('dialog', { name: 'Billing' })).not.toBeInTheDocument();
    });

    it('offers no Billing in the user menu', async () => {
      renderNewPost(undefined, NO_PLANS);
      const [menuButton] = await screen.findAllByRole('button', { name: 'User menu' });

      fireEvent.keyDown(menuButton, { key: 'Enter' });

      expect(await screen.findByRole('menuitem', { name: 'Account' })).toBeInTheDocument();
      expect(screen.queryByRole('menuitem', { name: 'Billing' })).not.toBeInTheDocument();
    });

    it('opens no Billing dialog when sent back from a checkout', async () => {
      renderNewPost({ checkoutStatus: 'success' }, NO_PLANS);

      expect(await writer()).toBeTruthy();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
  });
});
