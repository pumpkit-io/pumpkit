import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
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
vi.mock('@/services/inspirationAuthorService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/inspirationAuthorService')>()),
  inspirationAuthorService: {
    list: vi.fn().mockResolvedValue([]),
    add: vi.fn(),
    remove: vi.fn(),
    refresh: vi.fn(),
  },
}));
vi.mock('@/services/postService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/postService')>()),
  postService: { list: vi.fn(), get: vi.fn(), start: vi.fn(), addVersion: vi.fn() },
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
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { SELLS_PLANS } from '@/features/instance/testInstances';
import { TIME_ZONE } from '@/features/scheduledPosts/localTime';
import { billingService } from '@/services/billingService';
import {
  postService,
  type PostDetail,
  type PostCounts,
  type PostListItem,
  type PostsPage,
  type ScheduledPostSummary,
} from '@/services/postService';
import { xConnectionService } from '@/services/xConnectionService';
import { NOT_SUBSCRIBED, NO_POSTS, apiError, renderSignedIn } from './testing/signedInApp';

const COUNTS: PostCounts = { draft: 4, scheduled: 2, published: 7, failed: 1 };

/** Today at `hour` in the browser's time zone, `days` days from now, as an ISO instant. */
function at(days: number, hour: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  date.setHours(hour, 0, 0, 0);
  return date.toISOString();
}

function summary(extra: Partial<ScheduledPostSummary> = {}): ScheduledPostSummary {
  return {
    id: 'scheduled_post_01',
    state: 'scheduled',
    publishAt: at(1, 9),
    publishedAt: null,
    community: null,
    shareWithFollowers: false,
    failedReason: null,
    xPostUrl: null,
    ...extra,
  };
}

function item(id: string, parts: string[], extra: Partial<PostListItem> = {}): PostListItem {
  return {
    id,
    brief: 'ship small things',
    status: 'scheduled',
    parts,
    format: parts.length > 1 ? 'thread' : 'post',
    versionCount: 1,
    latestVersionAt: at(-1, 15),
    scheduledPost: summary(),
    ...extra,
  };
}

function page(posts: PostListItem[], nextOffset: number | null = null): PostsPage {
  return { posts, counts: COUNTS, nextOffset };
}

/**
 * The tab's pages in turn, each answer a page or a failure; the sidebar's own count reads,
 * a page of one Post, get the counts alone.
 */
function tabPages(...answers: (PostsPage | Error)[]) {
  vi.mocked(postService.list).mockImplementation(async (_status, _offset, limit) => {
    if (limit === 1) return page([]);
    const answer = answers.shift() ?? page([]);
    if (answer instanceof Error) throw answer;
    return answer;
  });
}

function currentPath() {
  return screen.getByRole('status', { name: 'Current path' }).textContent;
}

function tabs() {
  return within(screen.getByRole('navigation', { name: 'Posts by status' }));
}

async function row(name: string | RegExp) {
  return within(await screen.findByRole('listitem', { name }));
}

describe('Posts page', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(postService.list).mockReset().mockResolvedValue(NO_POSTS);
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue({
      handle: 'ada',
      charLimit: 280,
      needsReconnect: false,
      scheduledPostsWaiting: 0,
      photoUrl: null,
      offerPhoto: false,
    });
  });

  it.each(['/posts', '/scheduled'])('opens %s on the Scheduled tab', async (path) => {
    renderSignedIn(path);

    expect(await screen.findByRole('heading', { level: 1, name: 'Posts' })).toBeInTheDocument();
    expect(currentPath()).toBe('/posts/scheduled');
    await waitFor(() => expect(postService.list).toHaveBeenCalledWith('scheduled'));
  });

  it('shows which X account posts and the time zone the times are in', async () => {
    renderSignedIn('/posts/scheduled');

    const header = within(screen.getByRole('banner'));
    expect(await header.findByText('@ada')).toBeInTheDocument();
    expect(header.getByText(/Posting as/)).toHaveTextContent(
      `Posting as @ada · , times in ${TIME_ZONE}`,
    );
  });

  it('links to Settings to connect X when no X account is connected', async () => {
    vi.mocked(xConnectionService.get).mockResolvedValue(null);
    renderSignedIn('/posts/scheduled');

    const header = within(screen.getByRole('banner'));
    expect(await header.findByRole('link', { name: 'Connect X to post' })).toHaveAttribute(
      'href',
      '/settings',
    );
  });

  it('offers no X connection on an Instance without X', async () => {
    vi.mocked(xConnectionService.get).mockResolvedValue(null);
    renderSignedIn('/posts/scheduled', { instance: { ...SELLS_PLANS, x_connection: false } });

    const header = within(screen.getByRole('banner'));
    expect(await header.findByText(TIME_ZONE)).toBeInTheDocument();
    expect(header.queryByRole('link', { name: 'Connect X to post' })).not.toBeInTheDocument();
  });

  it('has a tab for each status with its count, each at its own address', async () => {
    vi.mocked(postService.list).mockResolvedValue(page([]));
    renderSignedIn('/posts/drafts');

    const drafts = await tabs().findByRole('link', { name: 'Drafts 4' });
    expect(drafts).toHaveAttribute('aria-current', 'page');
    expect(
      tabs()
        .getAllByRole('link')
        .map((link) => link.getAttribute('href')),
    ).toEqual(['/posts/scheduled', '/posts/drafts', '/posts/published', '/posts/failed']);
    expect(tabs().getByRole('link', { name: 'Scheduled 2' })).not.toHaveAttribute('aria-current');
    expect(tabs().getByRole('link', { name: 'Published 7' })).toBeInTheDocument();
    expect(tabs().getByRole('link', { name: 'Failed 1' })).toBeInTheDocument();
    expect(screen.getByText('Newest version first.')).toBeInTheDocument();
    expect(postService.list).toHaveBeenCalledWith('draft');

    fireEvent.click(tabs().getByRole('link', { name: 'Failed 1' }));

    await waitFor(() => expect(postService.list).toHaveBeenCalledWith('failed'));
    expect(currentPath()).toBe('/posts/failed');
    expect(screen.getByText('Most recently due first.')).toBeInTheDocument();
  });

  it("feeds the sidebar's Failed badge from the tab's counts", async () => {
    vi.mocked(postService.list).mockResolvedValue(page([]));
    renderSignedIn('/posts/scheduled');

    const nav = within(await screen.findByRole('navigation', { name: 'Main' }));
    expect(await nav.findByRole('link', { name: 'Posts, 1 failed' })).toBeInTheDocument();
  });

  describe('Scheduled', () => {
    it('lists each Post with its day and time, title, Format, Parts and Destination', async () => {
      vi.mocked(postService.list).mockResolvedValue(
        page([
          item('post_01', ['Ship small every week.\nIt compounds.', 'Part two.', 'Part three.']),
          item('post_02', ['Into the Community.'], {
            scheduledPost: summary({
              id: 'scheduled_post_02',
              publishAt: at(3, 14),
              community: {
                id: '1500',
                name: 'Indie Hackers',
                url: 'https://x.com/i/communities/1500',
              },
            }),
          }),
        ]),
      );
      renderSignedIn('/posts/scheduled');

      const thread = await row('Ship small every week.');
      expect(thread.getByText('Tomorrow')).toBeInTheDocument();
      expect(thread.getByText('9:00 AM')).toBeInTheDocument();
      expect(thread.getByText(/Thread · 3 parts · Your profile/)).toBeInTheDocument();
      expect(thread.getByText('Scheduled')).toBeInTheDocument();
      expect(thread.queryByText('It compounds.')).not.toBeInTheDocument();
      const community = await row('Into the Community.');
      expect(community.getByText('In 3 days')).toBeInTheDocument();
      expect(community.getByText('2:00 PM')).toBeInTheDocument();
      expect(community.getByText(/Single post · In the community/)).toBeInTheDocument();
      expect(community.getByRole('link', { name: 'Indie Hackers' })).toHaveAttribute(
        'href',
        'https://x.com/i/communities/1500',
      );
      expect(screen.getByText('Next to go out first.')).toBeInTheDocument();
    });

    it('says when a Post is being published', async () => {
      vi.mocked(postService.list).mockResolvedValue(
        page([
          item('post_01', ['Going out.'], { scheduledPost: summary({ state: 'publishing' }) }),
        ]),
      );
      renderSignedIn('/posts/scheduled');

      expect((await row('Going out.')).getByText('Publishing')).toBeInTheDocument();
    });

    it('expands a row into every Part with its count, the Destination and the time', async () => {
      vi.mocked(postService.list).mockResolvedValue(
        page([item('post_01', ['Ship small.\nSecond line.', 'Part two.'])]),
      );
      renderSignedIn('/posts/scheduled');
      const thread = await row('Ship small.');

      fireEvent.click(thread.getByRole('button', { name: 'Show every part' }));

      const first = within(thread.getByRole('listitem', { name: 'Part 1 of 2' }));
      expect(first.getByText(/Second line\./)).toBeInTheDocument();
      expect(first.getByText('24 / 280')).toBeInTheDocument();
      expect(
        within(thread.getByRole('listitem', { name: 'Part 2 of 2' })).getByText('9 / 280'),
      ).toBeInTheDocument();
      expect(thread.getByText(new RegExp(`9:00 AM \\(${TIME_ZONE}\\)`))).toBeInTheDocument();
      expect(thread.getByRole('button', { name: 'Hide the parts' })).toHaveAttribute(
        'aria-expanded',
        'true',
      );

      fireEvent.click(thread.getByRole('button', { name: 'Hide the parts' }));

      expect(thread.queryByRole('listitem', { name: 'Part 1 of 2' })).not.toBeInTheDocument();
    });

    it("opens the Post's page with the editor open from Edit on an expanded row", async () => {
      vi.mocked(postService.list).mockResolvedValue(page([item('post_01', ['Ship small.'])]));
      vi.mocked(postService.get).mockResolvedValue({
        id: 'post_01',
        brief: 'ship small things',
        status: 'scheduled',
        text: {
          format: 'post',
          parts: [{ text: 'Ship small.', charCount: 11, charLimit: 280 }],
          versionNumber: 1,
          edited: false,
        },
        versions: [
          {
            id: 'version_attempt_01',
            number: 1,
            feedback: null,
            format: 'post',
            parts: [{ text: 'Ship small.', charCount: 11, charLimit: 280 }],
            createdAt: '2026-10-10T12:00:30Z',
          },
        ],
        scheduledPost: {
          id: 'scheduled_post_01',
          parts: [{ text: 'Ship small.', live: false, xPostUrl: null }],
          state: 'scheduled',
          publishAt: at(1, 9),
          publishedAt: null,
          xPostUrl: null,
          failedReason: null,
          community: null,
          shareWithFollowers: false,
          createdAt: at(-1, 15),
        },
      });
      renderSignedIn('/posts/scheduled');
      const scheduled = await row('Ship small.');
      expect(scheduled.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();

      fireEvent.click(scheduled.getByRole('button', { name: 'Show every part' }));
      fireEvent.click(scheduled.getByRole('button', { name: 'Edit' }));

      expect(currentPath()).toBe('/posts/post_01');
      expect(
        await screen.findByRole('region', { name: 'Edit the scheduled post' }),
      ).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: 'Post text' })).toHaveValue('Ship small.');
    });

    it('offers no Edit on a row being published', async () => {
      vi.mocked(postService.list).mockResolvedValue(
        page([
          item('post_01', ['Ship small.'], { scheduledPost: summary({ state: 'publishing' }) }),
        ]),
      );
      renderSignedIn('/posts/scheduled');
      const scheduled = await row('Ship small.');

      fireEvent.click(scheduled.getByRole('button', { name: 'Show every part' }));

      expect(scheduled.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    });

    it("opens the Post's page from the row's title", async () => {
      vi.mocked(postService.list).mockResolvedValue(page([item('post_01', ['Ship small.'])]));
      vi.mocked(postService.get).mockReturnValue(new Promise(() => undefined));
      renderSignedIn('/posts/scheduled');

      fireEvent.click((await row('Ship small.')).getByRole('link', { name: 'Ship small.' }));

      expect(currentPath()).toBe('/posts/post_01');
    });

    it('says nothing is scheduled, pointing at the Drafts', async () => {
      renderSignedIn('/posts/scheduled');

      expect(await screen.findByText(/Nothing scheduled\./)).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Drafts' })).toHaveAttribute('href', '/posts/drafts');
    });
  });

  it('lists Drafts with their Format and how many Versions they have', async () => {
    vi.mocked(postService.list).mockResolvedValue(
      page([
        item('post_01', ['Revised twice.'], {
          status: 'draft',
          versionCount: 3,
          latestVersionAt: at(0, 8),
          scheduledPost: null,
        }),
      ]),
    );
    renderSignedIn('/posts/drafts');

    const draft = await row('Revised twice.');
    expect(draft.getByText('Today')).toBeInTheDocument();
    expect(draft.getByText('8:00 AM')).toBeInTheDocument();
    expect(draft.getByText('Single post · 3 versions')).toBeInTheDocument();
  });

  it('lists Published Posts with when they went out, where, and a link to X', async () => {
    vi.mocked(postService.list).mockResolvedValue(
      page([
        item('post_01', ['Went out.'], {
          status: 'published',
          scheduledPost: summary({
            state: 'published',
            publishAt: at(-2, 9),
            publishedAt: at(-2, 10),
            community: { id: '1500', name: null, url: 'https://x.com/i/communities/1500' },
            shareWithFollowers: true,
            xPostUrl: 'https://x.com/i/web/status/1890',
          }),
        }),
      ]),
    );
    renderSignedIn('/posts/published');

    const published = await row('Went out.');
    expect(published.getByText('2 days ago')).toBeInTheDocument();
    expect(published.getByText('10:00 AM')).toBeInTheDocument();
    expect(published.getByRole('link', { name: '1500' })).toBeInTheDocument();
    expect(published.getByText(/Shared with followers/)).toBeInTheDocument();
    expect(published.getByRole('link', { name: 'View on X' })).toHaveAttribute(
      'href',
      'https://x.com/i/web/status/1890',
    );
  });

  it('lists Failed Posts with the reason on one line', async () => {
    vi.mocked(postService.list).mockResolvedValue(
      page([
        item('post_01', ['Refused.'], {
          status: 'failed',
          scheduledPost: summary({
            state: 'failed',
            publishAt: at(-1, 9),
            failedReason: 'X refused the post: duplicate content.',
          }),
        }),
      ]),
    );
    renderSignedIn('/posts/failed');

    const failed = await row('Refused.');
    expect(failed.getByText('Yesterday')).toBeInTheDocument();
    expect(failed.getByText('X refused the post: duplicate content.')).toBeInTheDocument();
    expect(failed.queryByRole('link', { name: 'View on X' })).not.toBeInTheDocument();
  });

  it.each([
    ['/posts/drafts', /No drafts\./],
    ['/posts/published', /Nothing published yet\./],
    ['/posts/failed', /Nothing failed\./],
  ])('says %s is empty when it is', async (path, text) => {
    renderSignedIn(path);

    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it('shows more Posts at the end of a long tab until the last page', async () => {
    tabPages(
      page([item('post_01', ['First page.'])], 20),
      page([item('post_02', ['Second page.'])], null),
    );
    renderSignedIn('/posts/scheduled');
    await row('First page.');

    fireEvent.click(screen.getByRole('button', { name: 'Show more' }));

    expect(await row('Second page.')).toBeTruthy();
    expect(screen.getByRole('listitem', { name: 'First page.' })).toBeInTheDocument();
    expect(postService.list).toHaveBeenLastCalledWith('scheduled', 20);
    expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument();
  });

  it('offers to try again when the next page fails to load', async () => {
    tabPages(
      page([item('post_01', ['First page.'])], 20),
      apiError(500, 'boom'),
      page([item('post_02', ['Second page.'])], null),
    );
    renderSignedIn('/posts/scheduled');
    await row('First page.');

    fireEvent.click(screen.getByRole('button', { name: 'Show more' }));
    const alert = within(await screen.findByRole('alert'));
    expect(alert.getByText("Couldn't load more posts.")).toBeInTheDocument();
    fireEvent.click(alert.getByRole('button', { name: 'Try again' }));

    expect(await row('Second page.')).toBeTruthy();
  });

  it('says why the tab did not load, and loads it again on Try again', async () => {
    tabPages(apiError(500, 'The server is down.'), page([item('post_01', ['Back.'])]));
    renderSignedIn('/posts/scheduled');

    const alert = within(await screen.findByRole('alert'));
    expect(alert.getByText('The server is down.')).toBeInTheDocument();
    fireEvent.click(alert.getByRole('button', { name: 'Try again' }));

    expect(await row('Back.')).toBeTruthy();
  });

  describe('Recently opened', () => {
    function opened(id: string, text: string, extra: Partial<PostDetail> = {}): PostDetail {
      return {
        id,
        brief: 'ship small things',
        text: { format: 'post', parts: [], versionNumber: 2, edited: false },
        versions: [1, 2].map((number) => ({
          id: `${id}_v${number}`,
          number,
          feedback: number === 1 ? null : 'punchier',
          format: 'post' as const,
          parts: [{ text: `${text} v${number}`, charCount: 10, charLimit: 280 }],
          createdAt: at(0, 7 + number),
        })),
        status: 'draft',
        scheduledPost: null,
        ...extra,
      };
    }

    /** Opens each Post's page in turn, as the User would before coming back to Drafts. */
    async function open(...posts: PostDetail[]) {
      for (const post of posts) {
        vi.mocked(postService.get).mockResolvedValue(post);
        renderSignedIn(`/posts/${post.id}`);
        await screen.findByRole('article', { name: 'Text' });
        cleanup();
      }
    }

    function answer(...posts: PostDetail[]) {
      vi.mocked(postService.get).mockImplementation(async (id) => {
        const post = posts.find((p) => p.id === id);
        if (!post) throw apiError(404, 'Not found');
        return post;
      });
    }

    function section(name: string) {
      return within(screen.getByRole('region', { name }));
    }

    it('lists a Draft the User opened above every Draft, as its row in the list shows it', async () => {
      const post = opened('post_01', 'Revised once.');
      await open(post);
      answer(post);
      renderSignedIn('/posts/drafts');

      const recent = within(
        await screen.findByRole('region', { name: 'Recently opened' }),
      ).getByRole('listitem', { name: 'Revised once. v2' });
      expect(within(recent).getByText('Today')).toBeInTheDocument();
      expect(within(recent).getByText('9:00 AM')).toBeInTheDocument();
      expect(within(recent).getByText('Single post · 2 versions')).toBeInTheDocument();
      expect(
        section('Recently opened').getByText('Most recently opened first.'),
      ).toBeInTheDocument();
      expect(section('All drafts').getByText('Newest version first.')).toBeInTheDocument();
    });

    it('keeps the three Drafts opened last, the one opened again on top', async () => {
      const posts = ['One', 'Two', 'Three', 'Four'].map((text, i) => opened(`post_0${i}`, text));
      const [one, two, three, four] = posts as [PostDetail, PostDetail, PostDetail, PostDetail];
      await open(one, two, three, four, two);
      answer(...posts);
      renderSignedIn('/posts/drafts');

      const recent = within(await screen.findByRole('region', { name: 'Recently opened' }));
      expect(recent.getAllByRole('listitem').map((li) => li.getAttribute('aria-label'))).toEqual([
        'Two v2',
        'Four v2',
        'Three v2',
      ]);
    });

    it('drops a Draft not opened for 48 hours, and the section with it', async () => {
      vi.useFakeTimers({ toFake: ['Date'] });
      try {
        const post = opened('post_01', 'Left alone.');
        await open(post);
        answer(post);

        vi.setSystemTime(Date.now() + 47 * 60 * 60 * 1000);
        renderSignedIn('/posts/drafts');
        expect(await screen.findByRole('region', { name: 'Recently opened' })).toBeInTheDocument();
        cleanup();

        vi.setSystemTime(Date.now() + 2 * 60 * 60 * 1000);
        vi.mocked(postService.get).mockClear();
        renderSignedIn('/posts/drafts');
        expect(await screen.findByText(/No drafts/)).toBeInTheDocument();
        expect(screen.queryByRole('region', { name: 'Recently opened' })).not.toBeInTheDocument();
        expect(postService.get).not.toHaveBeenCalledWith('post_01');
      } finally {
        vi.useRealTimers();
      }
    });

    it('leaves out Posts no longer Drafts, and never lists one opened while scheduled', async () => {
      const kept = opened('post_01', 'Kept');
      const scheduled = opened('post_02', 'Scheduled since');
      const deleted = opened('post_03', 'Deleted since');
      const neverDraft = opened('post_04', 'Opened scheduled', { status: 'scheduled' });
      await open(kept, scheduled, deleted, neverDraft);
      answer(kept, { ...scheduled, status: 'scheduled' }, { ...neverDraft, status: 'draft' });
      renderSignedIn('/posts/drafts');

      const recent = within(await screen.findByRole('region', { name: 'Recently opened' }));
      expect(recent.getAllByRole('listitem').map((li) => li.getAttribute('aria-label'))).toEqual([
        'Kept v2',
      ]);
      cleanup();

      answer(kept, scheduled);
      renderSignedIn('/posts/drafts');

      const back = within(await screen.findByRole('region', { name: 'Recently opened' }));
      expect(back.getAllByRole('listitem').map((li) => li.getAttribute('aria-label'))).toEqual([
        'Scheduled since v2',
        'Kept v2',
      ]);
    });
  });
});
