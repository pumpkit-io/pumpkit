import {
  fireEvent,
  screen,
  waitFor,
  within,
  type BoundFunctions,
  type queries,
} from '@testing-library/react';
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
// Choose a Plan lands on Settings, which lists the API keys.
vi.mock('@/services/apiKeyService', () => ({
  apiKeyService: { list: vi.fn().mockResolvedValue([]), create: vi.fn(), revoke: vi.fn() },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
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
import {
  postService,
  type Part,
  type PostDetail,
  type Tell,
  type Version,
} from '@/services/postService';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import {
  LEVELSIO,
  NOT_SUBSCRIBED,
  SUBSCRIBED,
  apiError,
  renderSignedIn,
} from './testing/signedInApp';

const CONNECTED: XConnection = {
  handle: 'ada',
  charLimit: 280,
  needsReconnect: false,
  scheduledPostsWaiting: 0,
};

function part(text: string, charCount = text.length): Part {
  return { text, charCount, charLimit: 280 };
}

function version(number: number, texts: string[], extra: Partial<Version> = {}): Version {
  return {
    id: `version_attempt_0${number}`,
    number,
    feedback: number === 1 ? null : 'punchier',
    format: texts.length > 1 ? 'thread' : 'post',
    parts: texts.map((text) => part(text)),
    tells: [],
    ...extra,
  };
}

function draft(versions: Version[] = [version(1, ['the final text'])]): PostDetail {
  return {
    id: 'post_01',
    brief: 'ship small things',
    versions,
    status: 'draft',
    scheduledPost: null,
  };
}

function postWith(final: string, finalCharCount = final.length, tells: Tell[] = []): PostDetail {
  return draft([version(1, [final], { parts: [part(final, finalCharCount)], tells })]);
}

function threadWith(parts: Part[]): PostDetail {
  return draft([
    version(
      1,
      parts.map((p) => p.text),
      { parts },
    ),
  ]);
}

// The tests run in Europe/Rome (vitest.config.ts), two hours ahead of UTC in October.
const SCHEDULED: ScheduledPost = {
  id: 'scheduled_post_01',
  parts: [{ text: 'the final text', live: false, xPostUrl: null }],
  state: 'scheduled',
  publishAt: '2026-10-12T07:00:00Z',
  publishedAt: null,
  xPostUrl: null,
  failedReason: null,
  sourceVersionId: 'version_attempt_01',
  community: null,
  shareWithFollowers: false,
  createdAt: '2026-10-10T12:00:00Z',
};

/** A Post whose first of two Versions has `scheduledPost`, in the status it gives. */
function withScheduledPost(scheduledPost: ScheduledPost): PostDetail {
  const status =
    scheduledPost.state === 'publishing' || scheduledPost.state === 'scheduled'
      ? 'scheduled'
      : scheduledPost.state;
  return {
    ...draft([version(1, ['the final text']), version(2, ['the second text'])]),
    status,
    scheduledPost,
  };
}

function renderPost(post: PostDetail, instance: Instance = SELLS_PLANS) {
  vi.mocked(postService.get).mockResolvedValue(post);
  return renderSignedIn(`/posts/${post.id}`, { instance });
}

async function versionCard() {
  return within(await screen.findByRole('article', { name: /^Version \d+$/ }));
}

function panel(name: string) {
  return within(screen.getByRole('region', { name }));
}

describe('Post page', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([LEVELSIO]);
    vi.mocked(postService.get).mockReset();
    vi.mocked(postService.addVersion).mockReset();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(CONNECTED);
    vi.mocked(track).mockClear();
  });

  it('loads the Post from its address, under a breadcrumb with its status and title', async () => {
    renderPost(postWith('the final text\nand a second line'));

    await versionCard();
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent('Posts / Drafts / the final text');
    expect(heading).not.toHaveTextContent('second line');
    expect(postService.get).toHaveBeenCalledWith('post_01');
    expect(within(heading).getByRole('link', { name: 'Posts' })).toHaveAttribute('href', '/posts');
    expect(within(heading).getByRole('link', { name: 'Drafts' })).toHaveAttribute(
      'href',
      '/posts/drafts',
    );
    expect(
      (await screen.findByRole('link', { name: 'Persona: @levelsio' })).closest('header'),
    ).not.toBeNull();
    expect(panel('Brief').getByText('ship small things')).toBeInTheDocument();
  });

  it('shortens a long title with an ellipsis', async () => {
    renderPost(postWith(`${'word '.repeat(30)}end`));

    await versionCard();
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent(/word…$/);
    expect(heading).not.toHaveTextContent('end');
  });

  it('says so when the Post is not found', async () => {
    vi.mocked(postService.get).mockRejectedValue(apiError(404, 'Post not found.'));
    renderSignedIn('/posts/post_missing');

    expect(await screen.findByText(/this post isn.t here/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Write a new Post' })).toHaveAttribute('href', '/new');
  });

  it('offers to try again when the Post could not be loaded', async () => {
    vi.mocked(postService.get)
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce(postWith('the final text'));
    renderSignedIn('/posts/post_01');

    fireEvent.click(await screen.findByRole('button', { name: 'Try again' }));

    expect((await versionCard()).getByText('the final text')).toBeInTheDocument();
  });

  describe('Version card', () => {
    it('shows the Version number, its Format and its Part count', async () => {
      renderPost(threadWith([part('the first part'), part('the second part')]));

      const card = await versionCard();
      expect(card.getByRole('heading', { name: 'Version 1' })).toBeInTheDocument();
      expect(card.getByText('Thread · 2 Parts')).toBeInTheDocument();
    });

    it("shows each Part as an X post with the User's name, handle, place and count", async () => {
      renderPost(threadWith([part('the first part'), part('the second part', 290)]));

      const card = await versionCard();
      const parts = card
        .getAllByRole('listitem', { name: /^Part \d of 2$/ })
        .map((item) => within(item));
      expect(parts).toHaveLength(2);
      expect(await parts[0].findByText('Ada Lovelace')).toBeInTheDocument();
      expect(await parts[0].findByText('@ada')).toBeInTheDocument();
      expect(parts[0].getByText('1/2')).toBeInTheDocument();
      expect(parts[0].getByText('the first part')).toBeInTheDocument();
      expect(parts[0].getByText('14 / 280')).toBeInTheDocument();
      expect(parts[1].getByText('290 / 280')).toBeInTheDocument();
      expect(parts[1].getByText("10 characters over X's 280-character limit")).toBeInTheDocument();
    });

    it('shows a single post as one X post with no place in a Thread', async () => {
      renderPost(postWith('the final text'));

      const card = await versionCard();
      expect(card.getByText('Single post · 1 Part')).toBeInTheDocument();
      const only = card.getByRole('listitem', { name: 'Post' });
      expect(within(only).getByText('14 / 280')).toBeInTheDocument();
      expect(within(only).queryByText('1/1')).not.toBeInTheDocument();
    });

    it('says the slop check found no machine-written tells', async () => {
      renderPost(postWith('the final text'));

      expect((await versionCard()).getByText('No machine-written tells')).toBeInTheDocument();
    });

    it('lists the tells the slop check found', async () => {
      renderPost(
        postWith('the unfair advantage — distribution', undefined, [
          { name: 'em_dash', description: 'em dash' },
          { name: 'startup_cliche', description: 'startup-commentary cliche' },
        ]),
      );

      const card = await versionCard();
      expect(card.getByText('2 machine-written tells')).toBeInTheDocument();
      const tells = within(card.getByRole('list', { name: 'Machine-written tells' }));
      expect(tells.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
        'em dash',
        'startup-commentary cliche',
      ]);
    });

    it("shows the Scheduled post's text on the Version it was copied from", async () => {
      renderPost(
        withScheduledPost({
          ...SCHEDULED,
          parts: [{ text: 'the final text, edited', live: false, xPostUrl: null }],
        }),
      );

      const card = await versionCard();
      expect(card.getByRole('heading', { name: 'Version 1' })).toBeInTheDocument();
      expect(card.getByText('the final text, edited')).toBeInTheDocument();
      expect(card.queryByText('the final text')).not.toBeInTheDocument();
      expect(card.getByText('22 / 280')).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Next Version' }));

      expect((await versionCard()).getByText('the second text')).toBeInTheDocument();
    });
  });

  describe('Pager', () => {
    it('opens on the latest Version of a Draft and steps through every Version', async () => {
      renderPost(draft([version(1, ['the first text']), version(2, ['the second text'])]));

      expect((await versionCard()).getByText('the second text')).toBeInTheDocument();
      const pager = within(screen.getByRole('navigation', { name: 'Versions' }));
      expect(pager.getByText('Version 2 of 2')).toBeInTheDocument();
      expect(pager.getByText('"punchier"')).toBeInTheDocument();
      expect(pager.getByRole('button', { name: 'Next Version' })).toBeDisabled();

      fireEvent.click(pager.getByRole('button', { name: 'Previous Version' }));

      expect((await versionCard()).getByText('the first text')).toBeInTheDocument();
      expect(pager.getByText('From your brief')).toBeInTheDocument();
      expect(pager.getByRole('button', { name: 'Previous Version' })).toBeDisabled();

      fireEvent.click(pager.getByRole('button', { name: 'Version 2' }));

      expect((await versionCard()).getByText('the second text')).toBeInTheDocument();
    });

    it.each([
      ['scheduled', 'Scheduled'],
      ['publishing', 'Scheduled'],
      ['failed', 'Failed'],
      ['published', 'Published'],
    ] as const)(
      'marks the Version with a %s Scheduled post and prefixes its footer',
      async (state, label) => {
        renderPost(withScheduledPost({ ...SCHEDULED, state }));

        await versionCard();
        const pager = within(screen.getByRole('navigation', { name: 'Versions' }));
        expect(pager.getByRole('button', { name: `Version 1, ${label}` })).toHaveAttribute(
          'aria-current',
          'true',
        );
        expect(pager.getByText(`${label} · From your brief`)).toBeInTheDocument();

        fireEvent.click(pager.getByRole('button', { name: 'Version 2' }));

        expect(pager.getByText('"punchier"')).toBeInTheDocument();
      },
    );
  });

  describe('Copy post', () => {
    let writeText: ReturnType<typeof vi.fn>;
    beforeEach(() => {
      writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    });

    it('copies every Part of the Version on screen', async () => {
      renderPost(draft([version(1, ['the first text']), version(2, ['part one', 'part two'])]));
      await versionCard();

      fireEvent.click(panel('Draft').getByRole('button', { name: 'Copy post' }));

      expect(writeText).toHaveBeenCalledWith('part one\n\npart two');
      expect(await panel('Draft').findByRole('button', { name: 'Copied' })).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('post_final_copied');

      fireEvent.click(screen.getByRole('button', { name: 'Previous Version' }));
      fireEvent.click(await panel('Draft').findByRole('button', { name: /^Cop/ }));

      expect(writeText).toHaveBeenLastCalledWith('the first text');
    });

    it("copies the Scheduled post's text on the Version that has it", async () => {
      renderPost(
        withScheduledPost({
          ...SCHEDULED,
          parts: [{ text: 'the final text, edited', live: false, xPostUrl: null }],
        }),
      );
      await versionCard();

      fireEvent.click(panel('Scheduled').getByRole('button', { name: 'Copy post' }));

      expect(writeText).toHaveBeenCalledWith('the final text, edited');
    });
  });

  describe('Draft', () => {
    const versionTwo = version(2, ['the second final'], { feedback: 'make it shorter' });

    function sendFeedback(feedback: string) {
      const draftPanel = panel('Draft');
      fireEvent.change(draftPanel.getByLabelText('Feedback'), { target: { value: feedback } });
      fireEvent.click(draftPanel.getByRole('button', { name: 'Rewrite' }));
    }

    it('offers Feedback with a hint, the Format and Rewrite', async () => {
      renderPost(postWith('the final text'));
      await versionCard();

      const draftPanel = panel('Draft');
      expect(
        draftPanel.getByText(/everything you don.t mention stays as it is/i),
      ).toBeInTheDocument();
      expect(draftPanel.getByRole('radio', { name: 'Single post' })).toBeChecked();
      expect(await draftPanel.findByRole('button', { name: 'Rewrite' })).toBeDisabled();
    });

    it('writes the next Version from Feedback, then shows it and clears the box', async () => {
      let answer: (v: Version) => void = () => {};
      vi.mocked(postService.addVersion).mockReturnValue(
        new Promise((resolve) => (answer = resolve)),
      );
      renderPost(postWith('the first final'));
      await versionCard();
      await panel('Draft').findByRole('button', { name: 'Rewrite' });

      sendFeedback('  make it shorter ');

      const draftPanel = panel('Draft');
      expect(draftPanel.getByLabelText('Feedback')).toBeDisabled();
      expect(draftPanel.getByRole('button', { name: /writing/i })).toBeDisabled();
      expect(draftPanel.getByRole('status')).toHaveTextContent(/writing the next version/i);
      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'make it shorter', 'post');
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'feedback' });

      answer(versionTwo);

      expect(await screen.findByRole('heading', { name: 'Version 2' })).toBeInTheDocument();
      expect((await versionCard()).getByText('the second final')).toBeInTheDocument();
      expect(screen.getByText('"make it shorter"')).toBeInTheDocument();
      expect(draftPanel.getByLabelText('Feedback')).toHaveValue('');
      expect(draftPanel.getByLabelText('Feedback')).toBeEnabled();
    });

    it("starts the Format on the latest Version's and switches it with the Feedback", async () => {
      vi.mocked(postService.addVersion).mockResolvedValue({
        ...versionTwo,
        format: 'thread',
        parts: [part('part one'), part('part two'), part('part three')],
      });
      renderPost(postWith('the first final'));
      await versionCard();
      await panel('Draft').findByRole('button', { name: 'Rewrite' });
      const format = () => within(panel('Draft').getByRole('radiogroup', { name: 'Format' }));
      expect(format().getByRole('radio', { name: 'Single post' })).toBeChecked();

      fireEvent.click(format().getByRole('radio', { name: 'Thread' }));
      sendFeedback('expand it');

      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'expand it', 'thread');
      expect(await screen.findByText('Thread · 3 Parts')).toBeInTheDocument();
      expect(format().getByRole('radio', { name: 'Thread' })).toBeChecked();
    });

    it('starts the Format on Thread when the latest Version is a Thread', async () => {
      renderPost(threadWith([part('the first part'), part('the second part')]));
      await versionCard();

      const format = within(panel('Draft').getByRole('radiogroup', { name: 'Format' }));
      expect(format.getByRole('radio', { name: 'Thread' })).toBeChecked();
    });

    it('shows a failure and keeps the Feedback so it can be sent again', async () => {
      vi.mocked(postService.addVersion)
        .mockRejectedValueOnce(apiError(502, 'Writing the Post failed. Please try again.'))
        .mockResolvedValueOnce(versionTwo);
      renderPost(postWith('the first final'));
      await versionCard();
      await panel('Draft').findByRole('button', { name: 'Rewrite' });

      sendFeedback('make it shorter');

      const draftPanel = panel('Draft');
      expect(await draftPanel.findByRole('alert')).toHaveTextContent(
        'Writing the Post failed. Please try again.',
      );
      expect(draftPanel.getByLabelText('Feedback')).toHaveValue('make it shorter');
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'feedback' });

      fireEvent.click(draftPanel.getByRole('button', { name: 'Rewrite' }));

      expect(await screen.findByRole('heading', { name: 'Version 2' })).toBeInTheDocument();
      expect(draftPanel.queryByRole('alert')).not.toBeInTheDocument();
    });

    it.each([
      [404, 'Post not found.'],
      [409, 'This Post is scheduled, so it takes no Feedback.'],
    ])('does not count a refusal with a %i as a failed Version', async (status, detail) => {
      vi.mocked(postService.addVersion).mockRejectedValue(apiError(status, detail));
      renderPost(postWith('the first final'));
      await versionCard();
      await panel('Draft').findByRole('button', { name: 'Rewrite' });

      sendFeedback('make it shorter');

      expect(await panel('Draft').findByRole('alert')).toHaveTextContent(detail);
      expect(track).not.toHaveBeenCalledWith('post_version_failed', expect.anything());
    });

    it('says when the User can send Feedback again once they reach the hourly limit', async () => {
      vi.mocked(postService.addVersion).mockRejectedValue(
        apiError(429, "You've made 30 attempts at a Version in the last hour.", {
          retry_at: new Date(2026, 9, 6, 15, 42).toISOString(),
        }),
      );
      renderPost(postWith('the first final'));
      await versionCard();
      await panel('Draft').findByRole('button', { name: 'Rewrite' });

      sendFeedback('make it shorter');

      expect(
        await screen.findByText(
          "You've made 30 attempts at a Version in the last hour. You can write again at 3:42 PM.",
        ),
      ).toHaveAttribute('role', 'status');
      expect(panel('Draft').getByLabelText('Feedback')).toHaveValue('make it shorter');
    });

    it('shows a length counter only near the Feedback limit, and refuses Feedback over it', async () => {
      renderPost(postWith('the first final'));
      await versionCard();
      await panel('Draft').findByRole('button', { name: 'Rewrite' });
      const draftPanel = panel('Draft');
      const feedback = draftPanel.getByLabelText('Feedback');

      fireEvent.change(feedback, { target: { value: 'a'.repeat(1000) } });
      expect(draftPanel.queryByText(/100,000/)).not.toBeInTheDocument();

      fireEvent.change(feedback, { target: { value: '😀'.repeat(95_000) } });
      expect(draftPanel.getByText('95,000 / 100,000 characters')).toBeInTheDocument();
      expect(draftPanel.getByRole('button', { name: 'Rewrite' })).toBeEnabled();

      fireEvent.change(feedback, { target: { value: 'a'.repeat(100_003) } });
      expect(draftPanel.getByText('3 characters over the 100,000 limit')).toBeInTheDocument();
      expect(draftPanel.getByRole('button', { name: 'Rewrite' })).toBeDisabled();
    });

    it('asks a User who is not Subscribed to subscribe before Feedback', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderPost(postWith('the first final'));
      await versionCard();

      expect(await panel('Draft').findByRole('link', { name: /subscribe/i })).toBeInTheDocument();
      expect(panel('Draft').queryByRole('button', { name: 'Rewrite' })).not.toBeInTheDocument();
    });
  });

  describe('Scheduled', () => {
    it('says when it goes out, which Version, where and in which time zone, with no Feedback', async () => {
      renderPost(withScheduledPost(SCHEDULED));
      await versionCard();

      const scheduled = panel('Scheduled');
      expect(scheduled.getByText('Scheduled for Mon, Oct 12, 9:00 AM')).toBeInTheDocument();
      expect(scheduled.getByText('Version 1 · Your profile · Europe/Rome')).toBeInTheDocument();
      expect(scheduled.getByRole('button', { name: 'Copy post' })).toBeInTheDocument();
      expect(screen.queryByLabelText('Feedback')).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        'Posts / Scheduled / the final text',
      );
    });

    it('names the Community it goes to', async () => {
      renderPost(
        withScheduledPost({
          ...SCHEDULED,
          community: { id: '123', name: 'Indie makers', url: 'https://x.com/i/communities/123' },
        }),
      );
      await versionCard();

      expect(panel('Scheduled').getByRole('link', { name: 'Indie makers' })).toHaveAttribute(
        'href',
        'https://x.com/i/communities/123',
      );
    });
  });

  describe('Published', () => {
    const PUBLISHED: ScheduledPost = {
      ...SCHEDULED,
      state: 'published',
      publishedAt: '2026-10-12T07:00:14Z',
      xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
      parts: [
        {
          text: 'the final text',
          live: true,
          xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
        },
      ],
    };

    it('says when and where it was published, that it cannot change, and links to it on X', async () => {
      renderPost(withScheduledPost(PUBLISHED));
      await versionCard();

      const published = panel('Published');
      expect(published.getByText('Published Mon, Oct 12, 9:00 AM')).toBeInTheDocument();
      expect(published.getByText('Version 1 · Your profile')).toBeInTheDocument();
      expect(published.getByText(/published posts can.t be changed/i)).toBeInTheDocument();
      expect(published.getByRole('link', { name: 'View on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1890000000000000001',
      );
      expect(published.getByRole('button', { name: 'Copy post' })).toBeInTheDocument();
      expect(screen.queryByLabelText('Feedback')).not.toBeInTheDocument();
    });

    it('says whether a Community post was shared with followers', async () => {
      renderPost(
        withScheduledPost({
          ...PUBLISHED,
          community: { id: '123', name: null, url: 'https://x.com/i/communities/123' },
          shareWithFollowers: true,
        }),
      );
      await versionCard();

      expect(panel('Published').getByText('Shared with your followers')).toBeInTheDocument();
      expect(panel('Published').getByRole('link', { name: '123' })).toBeInTheDocument();
    });
  });

  describe('Failed', () => {
    const FAILED: ScheduledPost = {
      ...SCHEDULED,
      state: 'failed',
      failedReason: 'X refused the post: duplicate content.',
    };

    it('shows when it was due and why, then takes Feedback', async () => {
      vi.mocked(postService.addVersion).mockResolvedValue(
        version(3, ['the third text'], { feedback: 'not a duplicate' }),
      );
      renderPost(withScheduledPost(FAILED));
      await versionCard();

      const failed = panel('Failed');
      expect(
        failed.getByText('This Post didn’t go out. It was due Mon, Oct 12, 9:00 AM.'),
      ).toBeInTheDocument();
      expect(failed.getByText('X refused the post: duplicate content.')).toBeInTheDocument();
      await failed.findByRole('button', { name: 'Rewrite' });
      fireEvent.change(failed.getByLabelText('Feedback'), { target: { value: 'not a duplicate' } });
      fireEvent.click(failed.getByRole('button', { name: 'Rewrite' }));

      expect(await screen.findByRole('heading', { name: 'Version 3' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts / Failed /');
    });

    it('marks the Parts of a Thread already live on X', async () => {
      renderPost(
        withScheduledPost({
          ...FAILED,
          parts: [
            { text: 'Live one.', live: true, xPostUrl: 'https://x.com/i/web/status/1' },
            { text: 'Refused two.', live: false, xPostUrl: null },
          ],
        }),
      );

      const card = await versionCard();
      const [first, second] = card
        .getAllByRole('listitem', { name: /^Part \d of 2$/ })
        .map((item) => within(item));
      expect(first!.getByRole('link', { name: 'Part 1 is live on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1',
      );
      expect(second!.queryByText('Live on X')).not.toBeInTheDocument();
    });
  });

  describe('Draft: Post to…', () => {
    const COMMUNITY_ID = '1493446837214187523';
    const COMMUNITY_URL = `https://x.com/i/communities/${COMMUNITY_ID}`;
    const PUBLISHED: ScheduledPost = {
      ...SCHEDULED,
      state: 'published',
      publishedAt: '2026-10-10T12:00:14Z',
      xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
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
      vi.mocked(scheduledPostService.pastCommunities).mockReset().mockResolvedValue([]);
      // As when the Instance has no twitterapi.io: the Community comes back without a name.
      vi.mocked(scheduledPostService.lookUpCommunity)
        .mockReset()
        .mockImplementation(async (id) => ({
          id,
          name: null,
          url: `https://x.com/i/communities/${id}`,
        }));
      vi.mocked(xConnectionService.startAuthorization).mockReset();
      vi.mocked(redirectTo).mockReset();
    });

    type Dialog = BoundFunctions<typeof queries>;

    /** Opens "Post to…" on the Draft `post`, once its Version is on screen. */
    async function openPostTo(post: PostDetail = postWith('the final text')): Promise<Dialog> {
      renderPost(post);
      await versionCard();
      fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));
      return within(await screen.findByRole('dialog', { name: 'Post to…' }));
    }

    function scheduleAt(dialog: Dialog, date: string, time: string) {
      fireEvent.click(dialog.getByRole('radio', { name: 'Schedule' }));
      fireEvent.change(dialog.getByLabelText('Date'), { target: { value: date } });
      fireEvent.change(dialog.getByLabelText('Time'), { target: { value: time } });
    }

    async function pasteCommunity(dialog: Dialog, pasted: string) {
      fireEvent.click(dialog.getByRole('radio', { name: 'Community' }));
      fireEvent.change(dialog.getByLabelText('Community URL or ID'), {
        target: { value: pasted },
      });
      await vi.waitFor(() =>
        expect(dialog.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
      );
    }

    async function dialogClosed() {
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    }

    it('replaces Schedule and Post now with "Post to…"', async () => {
      renderPost(postWith('the final text'));
      await versionCard();

      const draftPanel = panel('Draft');
      expect(await draftPanel.findByRole('button', { name: 'Post to…' })).toBeInTheDocument();
      expect(draftPanel.queryByRole('button', { name: 'Schedule' })).not.toBeInTheDocument();
      expect(draftPanel.queryByRole('button', { name: 'Post now' })).not.toBeInTheDocument();
    });

    it('names the Version, its Format, its Part count and the X account it posts as', async () => {
      const dialog = await openPostTo(threadWith([part('the first part'), part('the second')]));

      expect(dialog.getByText('Version 1 · Thread · 2 Parts · as @ada')).toBeInTheDocument();
    });

    it("schedules the Version to the User's profile for a day and time in their time zone", async () => {
      vi.mocked(scheduledPostService.schedule).mockResolvedValue(SCHEDULED);
      const dialog = await openPostTo();

      expect(dialog.getByRole('radio', { name: 'My profile' })).toBeChecked();
      scheduleAt(dialog, '2026-10-12', '09:00');
      expect(dialog.getByText('In your time zone, Europe/Rome.')).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Schedule for Mon, Oct 12, 9:00 AM' }));

      await dialogClosed();
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
      expect(
        panel('Scheduled').getByText('Scheduled for Mon, Oct 12, 9:00 AM'),
      ).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts / Scheduled /');
    });

    it('sends the Version on screen, not the latest', async () => {
      vi.mocked(scheduledPostService.schedule).mockResolvedValue(SCHEDULED);
      renderPost(draft([version(1, ['the final text']), version(2, ['the second text'])]));
      await versionCard();
      fireEvent.click(screen.getByRole('button', { name: 'Previous Version' }));
      fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));

      expect(dialog.getByText('Version 1 · Single post · 1 Part · as @ada')).toBeInTheDocument();
      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      await dialogClosed();
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        '2026-10-12T07:00:00.000Z',
        { community: null, shareWithFollowers: false },
      );
    });

    it('shows why scheduling was refused and keeps the dialog open', async () => {
      vi.mocked(scheduledPostService.schedule).mockRejectedValue(
        apiError(422, 'Pick a time at least a minute from now.'),
      );
      const dialog = await openPostTo();

      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      expect(
        await dialog.findByText('Pick a time at least a minute from now.'),
      ).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: /^Schedule for/ })).toBeEnabled();
    });

    it('schedules into a pasted Community, shared with followers unless unticked', async () => {
      vi.mocked(scheduledPostService.schedule).mockResolvedValue({
        ...SCHEDULED,
        community: { id: COMMUNITY_ID, name: null, url: COMMUNITY_URL },
      });
      const dialog = await openPostTo();

      expect(dialog.queryByLabelText('Also share with followers')).not.toBeInTheDocument();
      await pasteCommunity(dialog, COMMUNITY_URL);
      expect(dialog.getByLabelText('Also share with followers')).toBeChecked();
      fireEvent.click(dialog.getByLabelText('Also share with followers'));
      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      await dialogClosed();
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        '2026-10-12T07:00:00.000Z',
        { community: { id: COMMUNITY_ID, name: null }, shareWithFollowers: false },
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

    it('schedules into a Community picked from the past ones, shared with followers', async () => {
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([
        { id: COMMUNITY_ID, name: 'Indie makers', url: COMMUNITY_URL },
      ]);
      vi.mocked(scheduledPostService.schedule).mockResolvedValue(SCHEDULED);
      const dialog = await openPostTo();

      fireEvent.click(dialog.getByRole('radio', { name: 'Community' }));
      expect(await dialog.findByLabelText('Which Community')).toHaveDisplayValue('Indie makers');
      expect(dialog.queryByLabelText('Community URL or ID')).not.toBeInTheDocument();
      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      await dialogClosed();
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        '2026-10-12T07:00:00.000Z',
        { community: { id: COMMUNITY_ID, name: 'Indie makers' }, shareWithFollowers: true },
      );
    });

    it('adds a Community by URL when the User has past ones', async () => {
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([
        { id: COMMUNITY_ID, name: 'Indie makers', url: COMMUNITY_URL },
      ]);
      const dialog = await openPostTo();

      fireEvent.click(dialog.getByRole('radio', { name: 'Community' }));
      const option = await dialog.findByRole<HTMLOptionElement>('option', {
        name: 'Add one by URL',
      });
      fireEvent.change(dialog.getByLabelText('Which Community'), {
        target: { value: option.value },
      });

      expect(dialog.getByLabelText('Community URL or ID')).toHaveValue('');
    });

    it('waits for a pasted Community to be one before it sends', async () => {
      const dialog = await openPostTo();

      fireEvent.click(dialog.getByRole('radio', { name: 'Community' }));
      fireEvent.change(dialog.getByLabelText('Community URL or ID'), {
        target: { value: 'not a community' },
      });

      expect(dialog.getByText(/that isn.t a community/i)).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Review and post' })).toBeDisabled();
    });

    it('shows every Part in order before posting now, then shows the Published Post', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...PUBLISHED,
        parts: [
          { text: 'the first part', live: true, xPostUrl: 'https://x.com/i/web/status/1' },
          { text: 'the second part', live: true, xPostUrl: 'https://x.com/i/web/status/2' },
        ],
      });
      const dialog = await openPostTo(
        threadWith([part('the first part'), part('the second part')]),
      );

      expect(dialog.getByRole('radio', { name: 'Now' })).toBeChecked();
      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));

      expect(dialog.getByText(/can.t be undone/i)).toBeInTheDocument();
      const parts = within(dialog.getByRole('list', { name: 'Parts' }))
        .getAllByRole('listitem')
        .map((item) => within(item));
      expect(parts).toHaveLength(2);
      expect(parts[0]!.getByText('Part 1')).toBeInTheDocument();
      expect(parts[0]!.getByText('the first part')).toBeInTheDocument();
      expect(parts[0]!.getByText('14 / 280')).toBeInTheDocument();
      expect(parts[1]!.getByText('Part 2')).toBeInTheDocument();
      expect(parts[1]!.getByText('the second part')).toBeInTheDocument();
      expect(scheduledPostService.postNow).not.toHaveBeenCalled();
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await dialogClosed();
      expect(scheduledPostService.postNow).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        { community: null, shareWithFollowers: false },
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'thread',
        part_count: 2,
        source: 'final',
        post_now: true,
        destination: 'profile',
      });
      expect(panel('Published').getByRole('link', { name: 'View on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1890000000000000001',
      );
    });

    it('goes back from the confirmation without posting', async () => {
      const dialog = await openPostTo();

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Back' }));

      expect(dialog.getByRole('radio', { name: 'Now' })).toBeChecked();
      expect(scheduledPostService.postNow).not.toHaveBeenCalled();
    });

    it('posts now into a Community, saying where it goes before the final yes', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...PUBLISHED,
        community: { id: COMMUNITY_ID, name: null, url: COMMUNITY_URL },
        shareWithFollowers: true,
      });
      const dialog = await openPostTo();

      await pasteCommunity(dialog, COMMUNITY_URL);
      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      expect(dialog.getByText(/from @ada into the Community/i)).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await dialogClosed();
      expect(scheduledPostService.postNow).toHaveBeenCalledWith(
        { sourceVersionId: 'version_attempt_01' },
        { community: { id: COMMUNITY_ID, name: null }, shareWithFollowers: true },
      );
      expect(panel('Published').getByText('Shared with your followers')).toBeInTheDocument();
    });

    it('shows a Community X refuses in the dialog without closing it', async () => {
      vi.mocked(scheduledPostService.postNow).mockRejectedValue(
        apiError(422, "X won't let @ada post in that Community. Join it on X first."),
      );
      const dialog = await openPostTo();

      await pasteCommunity(dialog, COMMUNITY_URL);
      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      expect(
        await dialog.findByText("X won't let @ada post in that Community. Join it on X first."),
      ).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Post now' })).toBeEnabled();
    });

    it('shows the Failed Post when posting now Failed', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...SCHEDULED,
        state: 'failed',
        failedReason: 'X refused the post: duplicate content.',
      });
      const dialog = await openPostTo();

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await dialogClosed();
      expect(
        panel('Failed').getByText('X refused the post: duplicate content.'),
      ).toBeInTheDocument();
    });

    it('says Pumpkit will retry when X was busy, then shows the Scheduled Post', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue(SCHEDULED);
      const dialog = await openPostTo();

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      expect(
        await dialog.findByText('X was busy. Pumpkit will keep trying for the next 15 minutes.'),
      ).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Done' }));

      await dialogClosed();
      expect(screen.getByRole('region', { name: 'Scheduled' })).toBeInTheDocument();
    });

    it("refuses a Part over X's limit by X's count", async () => {
      const dialog = await openPostTo(postWith('a'.repeat(290)));

      expect(
        dialog.getByText("The post is 10 characters over X's 280-character limit."),
      ).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Review and post' })).toBeDisabled();
    });

    it('lets a Part over 280 go to an X Premium account', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, charLimit: 25_000 });
      const dialog = await openPostTo(postWith('a'.repeat(290)));

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));

      expect(dialog.getByText('290 / 25,000')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Post now' })).toBeEnabled();
    });

    it('offers Connect X in place of Where and When without an X connection', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(null);
      vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
        'https://x.com/i/oauth2/authorize?state=s',
      );
      const dialog = await openPostTo();

      expect(dialog.getByText('Connect your X account to post this Post.')).toBeInTheDocument();
      expect(dialog.queryByRole('radio', { name: 'My profile' })).not.toBeInTheDocument();
      expect(dialog.queryByRole('radio', { name: 'Now' })).not.toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Connect X' }));
      await waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
      );
    });

    it('asks the User to reconnect X when X no longer accepts its access', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, needsReconnect: true });
      const dialog = await openPostTo();

      expect(dialog.getByText('Reconnect X to post this Post.')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Reconnect X' })).toBeInTheDocument();
    });

    it('sends a User who is not Subscribed to Choose a Plan', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderPost(postWith('the final text'));
      await versionCard();

      fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));

      expect(await screen.findByRole('region', { name: 'Choose a Plan' })).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('billing_choose_plan_opened', { source: 'post_to' });
    });

    it('sends a User who is no longer Subscribed to Choose a Plan', async () => {
      vi.mocked(scheduledPostService.postNow).mockRejectedValue(apiError(403, 'Subscribe first.'));
      const dialog = await openPostTo();
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      expect(await screen.findByRole('region', { name: 'Choose a Plan' })).toBeInTheDocument();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('billing_choose_plan_opened', { source: 'post_to' });
    });

    it('opens "Post to…" on an Instance that sells no Plans', async () => {
      renderPost(postWith('the final text'), { ...SELLS_PLANS, sells_plans: false });
      await versionCard();

      fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));

      expect(await screen.findByRole('dialog', { name: 'Post to…' })).toBeInTheDocument();
    });
  });
});
