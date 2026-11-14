import { act, fireEvent, screen, within } from '@testing-library/react';
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
  },
}));
vi.mock('@/services/briefService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/briefService')>()),
  briefService: { plan: vi.fn(), get: vi.fn(), write: vi.fn() },
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

import { briefService, type Brief, type Idea } from '@/services/briefService';
import { billingService } from '@/services/billingService';
import { WRITING_POLL_MS } from '@/services/postService';
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

function textOf(words: string) {
  return {
    format: 'post' as const,
    parts: [{ text: words, charCount: words.length, charLimit: 280 }],
    firstReply: false,
    versionNumber: 1,
    edited: false,
  };
}

const PAIN = 'Make sure the pain is real before you build';
const B2B = "B2B demand doesn't prove B2C demand";
const OAUTH = "Don't make OAuth integrations your core value";
const PRICE = 'Charge at least €20 a month';

function brief(posts: Partial<Record<1 | 2 | 3 | 4, Idea['post']>>): Brief {
  return {
    id: 'brief_01',
    text: 'I want to write about my SaaS failures',
    createdAt: '2026-10-10T12:00:30Z',
    ideas: [
      { ...idea(1, 'Three lessons from failed SaaS', null), id: 'idea_whole', wholeBrief: true },
      idea(1, PAIN, posts[1] ?? null),
      idea(2, B2B, posts[2] ?? null),
      idea(3, OAUTH, posts[3] ?? null),
      idea(4, PRICE, posts[4] ?? null),
    ],
  };
}

const written = (id: string, words: string) => ({
  id,
  writingState: null,
  text: textOf(words),
});
const beingWritten = (id: string) => ({ id, writingState: 'writing' as const, text: null });

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
        4: { id: 'post_4', writingState: 'not_written', text: null },
      }),
    );
    renderSignedIn('/briefs/brief_01');

    const list = await screen.findByRole('list');
    const cards = within(list).getAllByRole('listitem');
    expect(cards.map((card) => card.getAttribute('aria-label'))).toEqual([PAIN, B2B, PRICE]);
    expect(within(cards[0]!).getByText('I spent 5 months building.')).toBeInTheDocument();
    expect(within(cards[1]!).getByRole('status')).toHaveTextContent('Writing…');
    expect(within(cards[2]!).getByText(/couldn't be written/)).toBeInTheDocument();
    expect(within(cards[0]!).getByText('1')).toBeInTheDocument();
    expect(within(cards[2]!).getByText('4')).toBeInTheDocument();
    expect(screen.queryByText(OAUTH)).not.toBeInTheDocument();
    expect(within(cards[1]!).getByRole('link', { name: `Open “${B2B}”` })).toHaveAttribute(
      'href',
      '/posts/post_2',
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts from your brief');
    expect(screen.getByText('“I want to write about my SaaS failures”')).toBeInTheDocument();
    const main = within(screen.getByRole('main'));
    expect(main.getByRole('link', { name: 'New post' })).toHaveAttribute('href', '/new');
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

  it('says a brief that is not found is not here, and stops reading', async () => {
    vi.mocked(briefService.get)
      .mockResolvedValueOnce(brief({ 1: beingWritten('post_1') }))
      .mockRejectedValue(apiError(404, 'Brief not found.'));
    renderSignedIn('/briefs/brief_01');
    await screen.findByText('Writing…');

    await poll();
    await poll();

    expect(await screen.findByText(/This brief isn't here/)).toBeInTheDocument();
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
});
