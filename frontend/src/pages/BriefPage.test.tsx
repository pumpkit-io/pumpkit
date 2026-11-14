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
    fetchPlans: vi.fn().mockResolvedValue({
      plans: [],
      couponsEnabled: false,
      termsVersion: '2026-10-11',
      allowance: { generations: null, xPosts: null, linkXPosts: null },
      trial: null,
    }),
    openBillingPortal: vi.fn(),
    startTopUpCheckout: vi.fn(),
    subscribeNow: vi.fn(),
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
vi.mock('@/services/positioningService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/positioningService')>()),
  positioningService: {
    get: vi.fn().mockResolvedValue({ text: 'I post about bootstrapping.', canDraft: true }),
    save: vi.fn(),
    draft: vi.fn(),
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
    addVersion: vi.fn(),
    retry: vi.fn(),
    discard: vi.fn(),
  },
}));
vi.mock('@/services/briefService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/briefService')>()),
  briefService: {
    plan: vi.fn(),
    get: vi.fn(),
    write: vi.fn(),
    recent: vi.fn().mockResolvedValue([]),
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
vi.mock('@/services/usageService', () => ({ usageService: { get: vi.fn() } }));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { track } from '@/lib/analytics';
import { briefService, type Brief, type BriefPost, type Idea } from '@/services/briefService';
import { billingService } from '@/services/billingService';
import { WRITING_POLL_MS, postService, type PostText } from '@/services/postService';
import { usageService } from '@/services/usageService';
import { xConnectionService } from '@/services/xConnectionService';
import { SUBSCRIBED, apiError, currentPath, renderSignedIn } from './testing/signedInApp';

function idea(n: number, coreIdea: string, post: Idea['post']): Idea {
  return {
    id: `idea_${n}`,
    postingOrder: n,
    wholeBrief: false,
    plan: {
      coreIdea,
      takeaway: 'Ship it.',
      funnel: 'middle',
      desiredAction: 'bookmark',
      format: 'post',
      length: 'short',
      structure: 'few_lines',
    },
    post,
  };
}

function textOf(words: string, charLimit = 280): PostText {
  return {
    format: 'post',
    parts: [{ text: words, charCount: words.length, charLimit }],
    firstReply: false,
    versionNumber: 1,
    edited: false,
  };
}

const PAIN = 'Make sure the pain is real before you build';
const B2B = "B2B demand doesn't prove B2C demand";
const OAUTH = "Don't make OAuth integrations your core value";
const PRICE = 'Charge at least €20 a month';
const WHOLE = 'Three lessons from failed SaaS';

function brief(
  posts: Partial<Record<1 | 2 | 3 | 4, Idea['post']>>,
  wholePost: Idea['post'] = null,
): Brief {
  return {
    id: 'brief_01',
    text: 'I want to write about my SaaS failures',
    createdAt: '2026-10-10T12:00:30Z',
    ideas: [
      { ...idea(1, WHOLE, wholePost), id: 'idea_whole', wholeBrief: true },
      idea(1, PAIN, posts[1] ?? null),
      idea(2, B2B, posts[2] ?? null),
      idea(3, OAUTH, posts[3] ?? null),
      idea(4, PRICE, posts[4] ?? null),
    ],
    generationsLeft: 382,
  };
}

const written = (id: string, words: string, text: PostText = textOf(words)): BriefPost => ({
  id,
  writingState: null,
  status: 'draft',
  publishing: false,
  text,
  textMedia: text.parts.map(() => []),
});
const beingWritten = (id: string): BriefPost => ({
  id,
  writingState: 'writing',
  status: null,
  publishing: false,
  text: null,
  textMedia: [],
});
const notWritten = (id: string): BriefPost => ({
  id,
  writingState: 'not_written',
  status: null,
  publishing: false,
  text: null,
  textMedia: [],
});

/** The card of the Post whose core idea is `coreIdea`. */
async function card(coreIdea: string) {
  return within(await screen.findByRole('listitem', { name: coreIdea }));
}

/** The card of `coreIdea`'s Post in the list of Posts, once it is there. */
async function postCard(coreIdea: string) {
  const posts = within(await screen.findByRole('list', { name: 'Posts' }));
  return within(await posts.findByRole('listitem', { name: coreIdea }));
}

async function poll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);
  });
}

describe('Brief page', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(briefService.get).mockReset();
    vi.mocked(briefService.write).mockReset();
    vi.mocked(postService.retry).mockReset();
    vi.mocked(postService.discard).mockReset().mockResolvedValue();
    vi.mocked(track).mockClear();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(usageService.get).mockReset().mockResolvedValue({ allowance: null });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('lists the posts in posting order with their core idea, text or writing state, and Open', async () => {
    vi.mocked(briefService.get).mockResolvedValue(
      brief({
        1: written('post_1', 'I spent 5 months building.'),
        2: beingWritten('post_2'),
        4: notWritten('post_4'),
      }),
    );
    renderSignedIn('/briefs/brief_01');

    const list = await screen.findByRole('list', { name: 'Posts' });
    const cards = within(list).getAllByRole('listitem');
    expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual([PAIN, B2B, PRICE]);
    expect(within(cards[0]!).getByText('I spent 5 months building.')).toBeInTheDocument();
    expect(within(cards[1]!).getByRole('status')).toHaveTextContent('Writing…');
    expect(within(cards[2]!).getByText(/couldn't be written/)).toBeInTheDocument();
    expect(within(cards[0]!).getByText('1')).toBeInTheDocument();
    expect(within(cards[2]!).getByText('3')).toBeInTheDocument();
    expect(screen.getByText('3 of 4 written')).toBeInTheDocument();
    expect(within(list).queryByText(OAUTH)).not.toBeInTheDocument();
    expect(within(cards[1]!).getByRole('link', { name: `Open “${B2B}”` })).toHaveAttribute(
      'href',
      '/posts/post_2',
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts from your brief');
    expect(screen.getByText('“I want to write about my SaaS failures”')).toBeInTheDocument();
    const main = within(screen.getByRole('main'));
    expect(main.getByRole('link', { name: 'New post' })).toHaveAttribute('href', '/new');
  });

  it('shows a written card with its count against the limit, its plan in plain words, Open and "Post to…"', async () => {
    vi.mocked(briefService.get).mockResolvedValue(
      brief({
        1: written(
          'post_1',
          'I spent 5 months building.',
          textOf('I spent 5 months building.', 700),
        ),
      }),
    );
    renderSignedIn('/briefs/brief_01');

    const pain = await card(PAIN);
    const count = pain.getByText('26 / 700');
    expect(count).not.toHaveClass('text-destructive');
    expect(pain.getByText('Built for trust · aims for bookmarks · short')).toBeInTheDocument();
    expect(pain.getByRole('link', { name: `Open “${PAIN}”` })).toBeInTheDocument();
    fireEvent.click(pain.getByRole('button', { name: 'Post to…' }));

    expect(await screen.findByRole('dialog', { name: 'Post to…' })).toBeInTheDocument();
  });

  it('shows the count in the warning colour when the post is over the limit', async () => {
    const long = 'x'.repeat(300);
    vi.mocked(briefService.get).mockResolvedValue(brief({ 1: written('post_1', long) }));
    renderSignedIn('/briefs/brief_01');

    expect((await card(PAIN)).getByText('300 / 280')).toHaveClass('text-destructive');
  });

  it("shows a thread's first part and its part count", async () => {
    const thread: PostText = {
      format: 'thread',
      parts: ['Part one.', 'Part two.', 'Part three.'].map((text) => ({
        text,
        charCount: text.length,
        charLimit: 280,
      })),
      firstReply: false,
      versionNumber: 1,
      edited: false,
    };
    vi.mocked(briefService.get).mockResolvedValue(
      brief({ 1: written('post_1', 'Part one.', thread) }),
    );
    renderSignedIn('/briefs/brief_01');

    const pain = await card(PAIN);
    expect(pain.getByText('Part one.')).toBeInTheDocument();
    expect(pain.queryByText('Part two.')).not.toBeInTheDocument();
    expect(pain.getByText('Thread · 3 parts')).toBeInTheDocument();
    expect(pain.getByText('Built for trust · aims for bookmarks')).toBeInTheDocument();
  });

  it('shows a first reply under the text, labelled', async () => {
    const withReply: PostText = {
      ...textOf('The post.'),
      parts: [
        { text: 'The post.', charCount: 9, charLimit: 280 },
        { text: 'The link is here.', charCount: 17, charLimit: 280 },
      ],
      firstReply: true,
    };
    vi.mocked(briefService.get).mockResolvedValue(
      brief({ 1: written('post_1', 'The post.', withReply) }),
    );
    renderSignedIn('/briefs/brief_01');

    const reply = within((await card(PAIN)).getByRole('group', { name: 'First reply' }));
    expect(reply.getByText('The link is here.')).toBeInTheDocument();
  });

  it.each([
    ['scheduled', 'Scheduled'],
    ['published', 'Published'],
  ] as const)('shows a %s post\'s status badge in place of "Post to…"', async (status, badge) => {
    vi.mocked(briefService.get).mockResolvedValue(
      brief({ 1: { ...written('post_1', 'Gone out.'), status } }),
    );
    renderSignedIn('/briefs/brief_01');

    const pain = await card(PAIN);
    expect(pain.getByText(badge)).toBeInTheDocument();
    expect(pain.queryByRole('button', { name: 'Post to…' })).not.toBeInTheDocument();
    expect(pain.queryByRole('button', { name: /Discard/ })).not.toBeInTheDocument();
    expect(pain.getByRole('link', { name: `Open “${PAIN}”` })).toBeInTheDocument();
  });

  it("retries a post that couldn't be written, and reads the brief while it is written", async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: notWritten('post_1') }))
      .mockResolvedValue(brief({ 1: written('post_1', 'Written at last.') }));
    vi.mocked(postService.retry).mockResolvedValue({} as never);
    renderSignedIn('/briefs/brief_01');

    const pain = await card(PAIN);
    expect(pain.getByText("This post couldn't be written.")).toBeInTheDocument();
    fireEvent.click(pain.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Writing…')).toBeInTheDocument();
    expect(postService.retry).toHaveBeenCalledWith('post_1');
    expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'retry' });
    await poll();
    expect(await screen.findByText('Written at last.')).toBeInTheDocument();
  });

  it('reads the brief again when a retry is refused because the post moved on', async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: notWritten('post_1') }))
      .mockResolvedValue(brief({ 1: written('post_1', 'Written elsewhere.') }));
    vi.mocked(postService.retry).mockRejectedValue(apiError(409, 'This post is written.'));
    renderSignedIn('/briefs/brief_01');

    fireEvent.click((await card(PAIN)).getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Written elsewhere.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says why a retry failed', async () => {
    vi.mocked(briefService.get).mockResolvedValue(brief({ 1: notWritten('post_1') }));
    vi.mocked(postService.retry).mockRejectedValue(apiError(500, 'The server is down.'));
    renderSignedIn('/briefs/brief_01');

    fireEvent.click((await card(PAIN)).getByRole('button', { name: 'Retry' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The server is down.');
  });

  it('lists the ideas not written, and writes one without planning again', async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: written('post_1', 'First.') }))
      .mockResolvedValue(
        brief({ 1: written('post_1', 'First.'), 3: written('post_3', 'OAuth post.') }),
      );
    vi.mocked(briefService.write).mockResolvedValue(
      brief({ 1: written('post_1', 'First.'), 3: beingWritten('post_3') }),
    );
    renderSignedIn('/briefs/brief_01');

    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    expect(
      notWrittenList.getAllByRole('listitem').map((i) => i.getAttribute('aria-label')),
    ).toEqual([B2B, OAUTH, PRICE]);
    expect(screen.getByText('1 of 4 written')).toBeInTheDocument();
    fireEvent.click(notWrittenList.getByRole('button', { name: `Write “${OAUTH}”` }));

    const posts = within(await screen.findByRole('list', { name: 'Posts' }));
    expect(await posts.findByRole('listitem', { name: OAUTH })).toHaveTextContent('Writing…');
    expect(briefService.write).toHaveBeenCalledWith('brief_01', ['idea_3']);
    expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'brief' });
    await poll();
    expect(await screen.findByText('OAuth post.')).toBeInTheDocument();
  });

  it('offers the one post covering everything when it is the only idea, and goes to its post', async () => {
    const oneIdea: Brief = { ...brief({}), ideas: [brief({}).ideas[0]!] };
    const started: Brief = {
      ...oneIdea,
      ideas: [{ ...oneIdea.ideas[0]!, post: beingWritten('p') }],
    };
    vi.mocked(briefService.get).mockResolvedValueOnce(oneIdea).mockResolvedValue(started);
    vi.mocked(briefService.write).mockResolvedValue(started);
    renderSignedIn('/briefs/brief_01');

    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    fireEvent.click(notWrittenList.getByRole('button', { name: `Write “${WHOLE}”` }));

    await waitFor(() => expect(currentPath()).toBe('/posts/p'));
    expect(briefService.write).toHaveBeenCalledWith('brief_01', ['idea_whole']);
  });

  it('offers every idea and the one post covering everything while none is written', async () => {
    vi.mocked(briefService.get).mockResolvedValue(brief({}));
    renderSignedIn('/briefs/brief_01');

    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    expect(
      notWrittenList.getAllByRole('listitem').map((i) => i.getAttribute('aria-label')),
    ).toEqual([PAIN, B2B, OAUTH, PRICE, WHOLE]);
    expect(notWrittenList.getByText('One post covering everything')).toBeInTheDocument();
  });

  it('goes to the post when the brief has one post and no idea left to write', async () => {
    vi.mocked(briefService.get).mockResolvedValue(brief({}, written('post_w', 'Everything.')));
    renderSignedIn('/briefs/brief_01');

    await waitFor(() => expect(currentPath()).toBe('/posts/post_w'));
  });

  it('reads the brief again when an idea was written meanwhile', async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: written('post_1', 'First.') }))
      .mockResolvedValue(brief({ 1: written('post_1', 'First.'), 2: written('post_2', 'B2B.') }));
    vi.mocked(briefService.write).mockRejectedValue(
      apiError(409, 'One of these ideas is already written.', { code: 'IDEAS_ALREADY_WRITTEN' }),
    );
    renderSignedIn('/briefs/brief_01');

    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    fireEvent.click(notWrittenList.getByRole('button', { name: `Write “${B2B}”` }));

    expect(await screen.findByText('B2B.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the whole brief on "Show brief"', async () => {
    const text = `${'I want to write about my SaaS failures and what they taught me '.repeat(3)}the end.`;
    vi.mocked(briefService.get).mockResolvedValue({
      ...brief({ 1: written('post_1', 'First.') }),
      text,
    });
    renderSignedIn('/briefs/brief_01');

    const show = await screen.findByRole('button', { name: 'Show brief' });
    expect(screen.queryByText(text)).not.toBeInTheDocument();
    fireEvent.click(show);

    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide brief' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('reads the brief again while a post is being written, then stops', async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: beingWritten('post_1'), 2: beingWritten('post_2') }))
      .mockResolvedValueOnce(brief({ 1: written('post_1', 'First.'), 2: beingWritten('post_2') }))
      .mockResolvedValue(
        brief({ 1: written('post_1', 'First.'), 2: written('post_2', 'Second.') }),
      );
    renderSignedIn('/briefs/brief_01');
    expect(await screen.findAllByText('Writing…')).toHaveLength(2);

    await poll();
    expect(await screen.findByText('First.')).toBeInTheDocument();
    expect(screen.getAllByText('Writing…')).toHaveLength(1);
    await poll();
    expect(await screen.findByText('Second.')).toBeInTheDocument();
    await poll();
    await poll();

    expect(briefService.get).toHaveBeenCalledTimes(3);
  });

  it('waits twice as long after each failed read', async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: beingWritten('post_1') }))
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValue(brief({ 1: written('post_1', 'First.') }));
    renderSignedIn('/briefs/brief_01');
    await screen.findByText('Writing…');

    await poll();
    expect(briefService.get).toHaveBeenCalledTimes(2);
    await poll();
    expect(briefService.get).toHaveBeenCalledTimes(2);
    await poll();

    expect(await screen.findByText('First.')).toBeInTheDocument();
    expect(briefService.get).toHaveBeenCalledTimes(3);
  });

  it('stops reading once the page is left', async () => {
    vi.mocked(briefService.get).mockResolvedValue(brief({ 1: beingWritten('post_1') }));
    const { unmount } = renderSignedIn('/briefs/brief_01');
    await screen.findByText('Writing…');

    unmount();
    await poll();
    await poll();

    expect(briefService.get).toHaveBeenCalledTimes(1);
  });

  it("says a brief that is not found doesn't exist or isn't the User's, and stops reading", async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: beingWritten('post_1') }))
      .mockRejectedValue(apiError(404, 'Brief not found.'));
    renderSignedIn('/briefs/brief_01');
    await screen.findByText('Writing…');

    await poll();
    await poll();

    expect(
      await screen.findByText("This brief doesn't exist, or it isn't yours."),
    ).toBeInTheDocument();
    expect(briefService.get).toHaveBeenCalledTimes(2);
  });

  it('shows numbered placeholders while loading', async () => {
    vi.mocked(briefService.get).mockReturnValue(new Promise(() => {}));
    renderSignedIn('/briefs/brief_01');

    expect(await screen.findByRole('status', { name: 'Loading the brief' })).toBeInTheDocument();
  });

  it('says the brief could not be loaded, and retries', async () => {
    vi.mocked(briefService.get)
      .mockRejectedValueOnce(apiError(500, 'The server is down.'))
      .mockResolvedValue(brief({ 1: written('post_1', 'First.') }));
    renderSignedIn('/briefs/brief_01');

    expect(await screen.findByRole('alert')).toHaveTextContent("This brief couldn't be loaded.");
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByText('First.')).toBeInTheDocument();
    expect(currentPath()).toBe('/briefs/brief_01');
  });
  it('numbers the cards by their place among the posts, whatever idea they come from', async () => {
    vi.mocked(briefService.get).mockResolvedValue(
      brief({ 1: written('post_1', 'First.'), 3: written('post_3', 'Third idea.') }),
    );
    renderSignedIn('/briefs/brief_01');

    expect((await card(PAIN)).getByText('1')).toBeInTheDocument();
    expect((await card(OAUTH)).getByText('2')).toBeInTheDocument();
    expect(screen.getByText('2 of 4 written')).toBeInTheDocument();
  });

  it('disables "Post to…" while feedback rewrites a post', async () => {
    vi.mocked(briefService.get).mockResolvedValue(
      brief({ 1: { ...written('post_1', 'Old text.'), writingState: 'writing' } }),
    );
    renderSignedIn('/briefs/brief_01');

    expect((await card(PAIN)).getByRole('button', { name: 'Post to…' })).toBeDisabled();
  });

  it('shows "Publishing" on a post going out', async () => {
    vi.mocked(briefService.get).mockResolvedValue(
      brief({ 1: { ...written('post_1', 'Going.'), status: 'scheduled', publishing: true } }),
    );
    renderSignedIn('/briefs/brief_01');

    expect((await card(PAIN)).getByText('Publishing')).toBeInTheDocument();
  });

  it('says why a retry was refused when the post still is not written', async () => {
    const refusal = "This post was started before plans existed, so it can't be written again.";
    vi.mocked(briefService.get).mockResolvedValue(brief({ 1: notWritten('post_1') }));
    vi.mocked(postService.retry).mockRejectedValue(apiError(409, refusal));
    renderSignedIn('/briefs/brief_01');

    fireEvent.click((await card(PAIN)).getByRole('button', { name: 'Retry' }));

    expect(await (await card(PAIN)).findByRole('alert')).toHaveTextContent(refusal);
  });

  it('ignores a read that started before an idea was written', async () => {
    let answerStaleRead: (brief: Brief) => void = () => {};
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: beingWritten('post_1') }))
      .mockReturnValueOnce(new Promise((resolve) => (answerStaleRead = resolve)))
      .mockReturnValue(new Promise(() => {}));
    vi.mocked(briefService.write).mockResolvedValue(
      brief({ 1: beingWritten('post_1'), 2: beingWritten('post_2') }),
    );
    renderSignedIn('/briefs/brief_01');
    await screen.findByText('Writing…');
    await poll();
    expect(briefService.get).toHaveBeenCalledTimes(2);

    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    fireEvent.click(notWrittenList.getByRole('button', { name: `Write “${B2B}”` }));
    await (await postCard(B2B)).findByText('Writing…');
    await act(async () => answerStaleRead(brief({ 1: beingWritten('post_1') })));

    const posts = within(screen.getByRole('list', { name: 'Posts' }));
    expect(posts.getByRole('listitem', { name: B2B })).toHaveTextContent('Writing…');
  });

  it("shows a write's answer over a read answered before the write was", async () => {
    let answerWrite: (brief: Brief) => void = () => {};
    vi.mocked(briefService.get).mockResolvedValue(brief({ 1: beingWritten('post_1') }));
    vi.mocked(briefService.write).mockReturnValue(
      new Promise((resolve) => (answerWrite = resolve)),
    );
    renderSignedIn('/briefs/brief_01');
    await screen.findByText('Writing…');

    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    fireEvent.click(notWrittenList.getByRole('button', { name: `Write “${B2B}”` }));
    await poll();
    expect(briefService.get).toHaveBeenCalledTimes(2);
    await act(async () =>
      answerWrite(brief({ 1: beingWritten('post_1'), 2: beingWritten('post_2') })),
    );

    expect(await (await postCard(B2B)).findByText('Writing…')).toBeInTheDocument();
  });

  it('keeps the page when the brief cannot be read after a write', async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: written('post_1', 'First.') }))
      .mockRejectedValueOnce(apiError(500, 'The server is down.'))
      .mockResolvedValue(
        brief({ 1: written('post_1', 'First.'), 2: written('post_2', 'B2B post.') }),
      );
    vi.mocked(briefService.write).mockResolvedValue(
      brief({ 1: written('post_1', 'First.'), 2: beingWritten('post_2') }),
    );
    renderSignedIn('/briefs/brief_01');

    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    fireEvent.click(notWrittenList.getByRole('button', { name: `Write “${B2B}”` }));
    await (await postCard(B2B)).findByText('Writing…');
    await poll();

    expect(screen.getByText('First.')).toBeInTheDocument();
    expect(screen.queryByText("This brief couldn't be loaded.")).not.toBeInTheDocument();
    await poll();
    await poll();
    expect(await screen.findByText('B2B post.')).toBeInTheDocument();
  });

  it('keeps two requests in flight apart, with their own failures', async () => {
    let failRetry: (e: unknown) => void = () => {};
    vi.mocked(briefService.get).mockResolvedValue(brief({ 1: notWritten('post_1') }));
    vi.mocked(postService.retry).mockReturnValue(new Promise((_, reject) => (failRetry = reject)));
    vi.mocked(briefService.write).mockRejectedValue(apiError(500, 'Writing B2B failed.'));
    renderSignedIn('/briefs/brief_01');

    fireEvent.click((await card(PAIN)).getByRole('button', { name: 'Retry' }));
    const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
    fireEvent.click(notWrittenList.getByRole('button', { name: `Write “${B2B}”` }));

    expect(await notWrittenList.findByRole('alert')).toHaveTextContent('Writing B2B failed.');
    expect((await card(PAIN)).getByRole('button', { name: 'Retrying…' })).toBeDisabled();
    await act(async () => failRetry(apiError(500, 'Retrying failed.')));

    expect(await (await card(PAIN)).findByRole('alert')).toHaveTextContent('Retrying failed.');
    expect(notWrittenList.getByRole('alert')).toHaveTextContent('Writing B2B failed.');
  });
  describe('discarding a draft', () => {
    it('asks first, then discards it: its idea is offered again and the cards close up', async () => {
      vi.mocked(briefService.get)
        .mockResolvedValueOnce(
          brief({
            1: written('post_1', 'Pain post.'),
            2: written('post_2', 'B2B post.'),
            3: written('post_3', 'OAuth post.'),
          }),
        )
        .mockResolvedValue(
          brief({ 1: written('post_1', 'Pain post.'), 3: written('post_3', 'OAuth post.') }),
        );
      renderSignedIn('/briefs/brief_01');
      expect(await screen.findByText('3 of 4 written')).toBeInTheDocument();

      fireEvent.click((await card(B2B)).getByRole('button', { name: `Discard “${B2B}”` }));
      const dialog = within(await screen.findByRole('alertdialog'));
      expect(dialog.getByText('Discard this post?')).toBeInTheDocument();
      expect(dialog.getByText('Its versions are deleted for good.')).toBeInTheDocument();
      expect(postService.discard).not.toHaveBeenCalled();
      fireEvent.click(dialog.getByRole('button', { name: 'Discard' }));

      const notWrittenList = within(await screen.findByRole('list', { name: 'Not written' }));
      expect(notWrittenList.getByRole('listitem', { name: B2B })).toBeInTheDocument();
      expect(postService.discard).toHaveBeenCalledWith('post_2');
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      const cards = within(screen.getByRole('list', { name: 'Posts' })).getAllByRole('listitem');
      expect(cards.map((c) => c.getAttribute('aria-label'))).toEqual([PAIN, OAUTH]);
      expect(within(cards[1]!).getByText('2')).toBeInTheDocument();
      expect(screen.getByText('2 of 4 written')).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('post_discarded', { from: 'brief_page' });
      await waitFor(() =>
        expect(screen.getByRole('heading', { name: 'Not written' })).toHaveFocus(),
      );
    });

    it('keeps the post when the User changes their mind', async () => {
      vi.mocked(briefService.get).mockResolvedValue(
        brief({ 1: written('post_1', 'Pain post.'), 2: written('post_2', 'B2B post.') }),
      );
      renderSignedIn('/briefs/brief_01');

      fireEvent.click((await card(B2B)).getByRole('button', { name: `Discard “${B2B}”` }));
      fireEvent.click(
        within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Keep it' }),
      );

      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
      expect(postService.discard).not.toHaveBeenCalled();
      expect((await card(B2B)).getByText('B2B post.')).toBeInTheDocument();
    });

    it('says why in the dialog when discarding is refused', async () => {
      vi.mocked(briefService.get).mockResolvedValue(
        brief({ 1: written('post_1', 'Pain post.'), 2: written('post_2', 'B2B post.') }),
      );
      vi.mocked(postService.discard).mockRejectedValue(
        apiError(409, "This post is scheduled, so it can't be discarded. Unschedule it first."),
      );
      renderSignedIn('/briefs/brief_01');

      fireEvent.click((await card(B2B)).getByRole('button', { name: `Discard “${B2B}”` }));
      const dialog = within(await screen.findByRole('alertdialog'));
      fireEvent.click(dialog.getByRole('button', { name: 'Discard' }));

      expect(await dialog.findByRole('alert')).toHaveTextContent(
        "This post is scheduled, so it can't be discarded. Unschedule it first.",
      );
      expect(track).not.toHaveBeenCalledWith('post_discarded', expect.anything());
    });

    it('offers no discard on a post being written or not written', async () => {
      vi.mocked(briefService.get).mockResolvedValue(
        brief({ 1: beingWritten('post_1'), 2: notWritten('post_2') }),
      );
      renderSignedIn('/briefs/brief_01');

      expect((await card(PAIN)).queryByRole('button', { name: /Discard/ })).not.toBeInTheDocument();
      expect((await card(B2B)).queryByRole('button', { name: /Discard/ })).not.toBeInTheDocument();
    });
  });
});
