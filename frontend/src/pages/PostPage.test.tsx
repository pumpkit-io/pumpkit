import {
  act,
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
    list: vi.fn().mockResolvedValue({
      posts: [],
      counts: { draft: 0, scheduled: 0, published: 0, failed: 0 },
      nextOffset: null,
    }),
    get: vi.fn(),
    start: vi.fn(),
    addVersion: vi.fn(),
    restoreVersion: vi.fn(),
    saveText: vi.fn(),
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
    edit: vi.fn(),
    cancel: vi.fn(),
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
import { TEXT_SAVE_PAUSE_MS, TEXT_SAVE_RETRY_MS } from '@/features/posts/useTextAutosave';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import {
  postService,
  textOf,
  type Part,
  type PostDetail,
  type Tell,
  type Version,
} from '@/services/postService';
import {
  scheduledPostService,
  type Community,
  type ScheduledPost,
} from '@/services/scheduledPostService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import {
  LEVELSIO,
  NOT_SUBSCRIBED,
  NO_POSTS,
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
    createdAt: `2026-10-10T0${number}:00:00Z`,
    ...extra,
  };
}

/** `post` with `versions`, its Text set from the last of them, as the server sets it. */
function withVersions<P extends PostDetail>(post: P, versions: Version[]): P {
  const latest = versions[versions.length - 1]!;
  return { ...post, versions, text: textOf(latest) };
}

function draft(versions: Version[] = [version(1, ['the final text'])]): PostDetail {
  return withVersions(
    {
      id: 'post_01',
      brief: 'ship small things',
      text: null,
      versions: [],
      status: 'draft',
      scheduledPost: null,
    },
    versions,
  );
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
  community: null,
  shareWithFollowers: false,
  createdAt: '2026-10-10T12:00:00Z',
};

/** A Post with two Versions and `scheduledPost`, in the status it gives. */
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

async function textCard() {
  return within(await screen.findByRole('article', { name: 'Text' }));
}

function panel(name: string) {
  return within(screen.getByRole('region', { name }));
}

type Dialog = BoundFunctions<typeof queries>;

function scheduleAt(dialog: Dialog, date: string, time: string) {
  fireEvent.click(dialog.getByRole('radio', { name: 'Schedule' }));
  fireEvent.change(dialog.getByLabelText('Date'), { target: { value: date } });
  fireEvent.change(dialog.getByLabelText('Time'), { target: { value: time } });
}

async function dialogClosed() {
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
}

describe('Post page', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(inspirationAuthorService.list).mockReset().mockResolvedValue([LEVELSIO]);
    vi.mocked(postService.get).mockReset();
    vi.mocked(postService.addVersion).mockReset();
    vi.mocked(postService.restoreVersion).mockReset();
    vi.mocked(postService.list).mockReset().mockResolvedValue(NO_POSTS);
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(CONNECTED);
    vi.mocked(track).mockClear();
  });

  it('loads the Post from its address, under a breadcrumb with its status and title', async () => {
    renderPost(postWith('the final text\nand a second line'));

    await textCard();
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
  });

  it('shortens a long title with an ellipsis', async () => {
    renderPost(postWith(`${'word '.repeat(30)}end`));

    await textCard();
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent(/word…$/);
    expect(heading).not.toHaveTextContent('end');
  });

  it('shows a card-shaped placeholder and the dock, disabled, while the Post loads', async () => {
    vi.mocked(postService.get).mockReturnValue(new Promise(() => {}));
    renderSignedIn('/posts/post_01');

    expect(await screen.findByRole('status', { name: 'Loading the Post' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Text' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Feedback' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send Feedback' })).toBeDisabled();
  });

  it('says so when the Post is not found', async () => {
    vi.mocked(postService.get).mockRejectedValue(apiError(404, 'Post not found.'));
    renderSignedIn('/posts/post_missing');

    expect(await screen.findByText(/this post isn.t here/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Write a new Post' })).toHaveAttribute('href', '/new');
    expect(screen.queryByRole('textbox', { name: 'Feedback' })).not.toBeInTheDocument();
  });

  it('offers to try again when the Post could not be loaded', async () => {
    vi.mocked(postService.get)
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce(postWith('the final text'));
    renderSignedIn('/posts/post_01');

    fireEvent.click(await screen.findByRole('button', { name: 'Try again' }));

    expect((await textCard()).getByText('the final text')).toBeInTheDocument();
  });

  describe('Text card', () => {
    it("shows each Part as an X post with the User's name, handle, place and count", async () => {
      renderPost(threadWith([part('the first part'), part('the second part', 290)]));

      const card = await textCard();
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

    it('shows a single post with no Version number, Format, Part count or place', async () => {
      renderPost(postWith('the final text'));

      const card = await textCard();
      const only = card.getByRole('listitem', { name: 'Post' });
      expect(within(only).getByText('14 / 280')).toBeInTheDocument();
      expect(within(only).queryByText('1/1')).not.toBeInTheDocument();
      expect(card.queryByText(/Version 1/)).not.toBeInTheDocument();
      expect(card.queryByText(/Single post|1 Part/)).not.toBeInTheDocument();
    });

    it('shows no machine-written tells', async () => {
      renderPost(
        postWith('the unfair advantage — distribution', undefined, [
          { name: 'em_dash', description: 'em dash' },
        ]),
      );

      await textCard();
      expect(screen.queryByText(/machine-written/i)).not.toBeInTheDocument();
      expect(screen.queryByText('em dash')).not.toBeInTheDocument();
    });

    it("shows the Post's Text, not its latest Version", async () => {
      renderPost({
        ...draft([version(1, ['the first text']), version(2, ['the second text'])]),
        text: {
          format: 'post',
          parts: [part('the text on screen')],
          versionNumber: 1,
          edited: true,
        },
      });

      const card = await textCard();
      expect(card.getByText('the text on screen')).toBeInTheDocument();
      expect(screen.queryByText('the second text')).not.toBeInTheDocument();
    });

    it("shows the Scheduled post's text on a Scheduled Post", async () => {
      renderPost(
        withScheduledPost({
          ...SCHEDULED,
          parts: [{ text: 'the final text, edited', live: false, xPostUrl: null }],
        }),
      );

      const card = await textCard();
      expect(card.getByText('the final text, edited')).toBeInTheDocument();
      expect(card.getByText('22 / 280')).toBeInTheDocument();
    });
  });

  describe('Copy', () => {
    let writeText: ReturnType<typeof vi.fn>;
    beforeEach(() => {
      writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    });

    it('copies a single post as it is, then says so for two seconds', async () => {
      renderPost(postWith('the final text\n\nwith a gap'));
      const card = await textCard();

      fireEvent.click(card.getByRole('button', { name: 'Copy post' }));

      expect(writeText).toHaveBeenCalledWith('the final text\n\nwith a gap');
      expect(await card.findByRole('status')).toHaveTextContent('Copied');
      expect(track).toHaveBeenCalledWith('post_final_copied');
      await waitFor(() => expect(card.getByRole('status')).toHaveTextContent(''), {
        timeout: 2500,
      });
    });

    it('copies a Thread with a line holding only --- between its Parts', async () => {
      renderPost(threadWith([part('part one'), part('part two'), part('part three')]));
      const card = await textCard();

      fireEvent.click(card.getByRole('button', { name: 'Copy post' }));

      expect(writeText).toHaveBeenCalledWith('part one\n\n---\n\npart two\n\n---\n\npart three');
      expect(await card.findByText('Copied')).toBeInTheDocument();
    });

    it("copies the Scheduled post's text on a Scheduled Post", async () => {
      renderPost(
        withScheduledPost({
          ...SCHEDULED,
          parts: [{ text: 'the final text, edited', live: false, xPostUrl: null }],
        }),
      );
      const card = await textCard();

      fireEvent.click(card.getByRole('button', { name: 'Copy post' }));

      expect(writeText).toHaveBeenCalledWith('the final text, edited');
      expect(await card.findByText('Copied')).toBeInTheDocument();
    });

    it('says to select the text and copy it when the browser refuses', async () => {
      writeText.mockRejectedValue(new Error('NotAllowedError'));
      renderPost(postWith('the final text'));
      const card = await textCard();

      fireEvent.click(card.getByRole('button', { name: 'Copy post' }));

      expect(await screen.findByRole('tooltip')).toHaveTextContent(
        "Couldn't copy. Select the text and copy it yourself.",
      );
      expect(track).not.toHaveBeenCalledWith('post_final_copied');
    });
  });

  describe('Origin line', () => {
    it('says the Text came from the Brief, and opens the full Brief', async () => {
      renderPost(postWith('the final text'));
      await textCard();

      fireEvent.click(panel('Draft').getByRole('button', { name: 'V1 · From your Brief' }));

      const brief = await screen.findByRole('dialog', { name: 'Brief' });
      expect(within(brief).getByText('ship small things')).toBeInTheDocument();
      fireEvent.keyDown(brief, { key: 'Escape' });
      await dialogClosed();
    });

    it("names the Feedback the Text's Version came from, and opens it in full", async () => {
      renderPost(
        draft([
          version(1, ['the first text']),
          version(2, ['the second text'], { feedback: 'Shorter, and drop the last line.' }),
        ]),
      );
      await textCard();

      fireEvent.click(
        panel('Draft').getByRole('button', {
          name: 'V2 · From Feedback: “Shorter, and drop the last line.”',
        }),
      );

      const feedback = await screen.findByRole('dialog', { name: 'Feedback' });
      expect(within(feedback).getByText('Shorter, and drop the last line.')).toBeInTheDocument();
      fireEvent.pointerDown(document.body);
      await dialogClosed();
    });

    it('follows the Version the Text came from, and says when it was edited', async () => {
      renderPost({
        ...draft([version(1, ['the first text']), version(2, ['the second text'])]),
        text: { format: 'post', parts: [part('changed')], versionNumber: 1, edited: true },
      });
      await textCard();

      expect(
        panel('Draft').getByRole('button', { name: 'V1 · From your Brief · edited' }),
      ).toBeInTheDocument();
    });
  });

  describe('History', () => {
    const THREE = [
      version(1, ['the first text']),
      version(2, ['the second text'], { feedback: 'Punchier hook' }),
      version(3, ['the third text'], {
        feedback: 'Shorter, and drop the last line.\nAlso no hashtags.',
      }),
    ];

    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(new Date('2026-10-10T05:00:00Z'));
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    async function openHistory(dockName = 'Draft') {
      await textCard();
      fireEvent.click(panel(dockName).getByRole('button', { name: 'History' }));
      return within(await screen.findByRole('dialog', { name: 'History' }));
    }

    function rows(history: Dialog) {
      return history.getAllByRole('listitem').map((row) => within(row));
    }

    it('lists every Version newest first, with its Brief or Feedback and when it was written', async () => {
      renderPost(draft(THREE));

      const history = await openHistory();

      const [third, second, first] = rows(history);
      expect(third!.getByText('Version 3')).toBeInTheDocument();
      expect(third!.getByText('Feedback: “Shorter, and drop the last line.”')).toBeInTheDocument();
      expect(third!.getByText('On screen')).toBeInTheDocument();
      expect(second!.getByText('Feedback: “Punchier hook”')).toBeInTheDocument();
      expect(second!.getByText('3h ago')).toBeInTheDocument();
      expect(first!.getByText('Version 1')).toBeInTheDocument();
      expect(first!.getByText('Brief: “ship small things”')).toBeInTheDocument();
      expect(first!.getByText('4h ago')).toBeInTheDocument();
      expect(history.getByRole('button', { name: /^Version 3/ })).toHaveAttribute(
        'aria-current',
        'true',
      );
      expect(history.getByRole('button', { name: /^Version 2/ })).not.toHaveAttribute(
        'aria-current',
      );
    });

    it('expands a row to its full Brief or Feedback', async () => {
      renderPost(draft(THREE));
      const history = await openHistory();

      const expand = history.getByRole('button', { name: 'Show the full Feedback of Version 3' });
      expect(expand).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(expand);

      expect(expand).toHaveAttribute('aria-expanded', 'true');
      expect(
        history.getByText(
          (_, node) =>
            node?.textContent === 'Shorter, and drop the last line.\nAlso no hashtags.' &&
            node.tagName === 'P',
        ),
      ).toBeInTheDocument();
      expect(postService.restoreVersion).not.toHaveBeenCalled();
    });

    it('restores a Version on click, and the Text and the origin line follow', async () => {
      vi.mocked(postService.restoreVersion).mockResolvedValue(textOf(THREE[1]!));
      renderPost(draft(THREE));
      const history = await openHistory();

      fireEvent.click(history.getByRole('button', { name: /^Version 2/ }));

      expect(await (await textCard()).findByText('the second text')).toBeInTheDocument();
      expect(postService.restoreVersion).toHaveBeenCalledWith('post_01', 2);
      expect(
        panel('Draft').getByRole('button', { name: 'V2 · From Feedback: “Punchier hook”' }),
      ).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('version_restored', { source: 'history' });
      await dialogClosed();
    });

    it('leaves the Text be when its own Version is clicked', async () => {
      renderPost(draft(THREE));
      const history = await openHistory();

      fireEvent.click(history.getByRole('button', { name: /^Version 3/ }));

      await dialogClosed();
      expect(postService.restoreVersion).not.toHaveBeenCalled();
    });

    it('restores the Version on screen over edits to it', async () => {
      vi.mocked(postService.restoreVersion).mockResolvedValue(textOf(THREE[2]!));
      renderPost({
        ...draft(THREE),
        text: { format: 'post', parts: [part('changed by hand')], versionNumber: 3, edited: true },
      });
      const history = await openHistory();

      fireEvent.click(history.getByRole('button', { name: /^Version 3/ }));

      expect(await (await textCard()).findByText('the third text')).toBeInTheDocument();
      expect(postService.restoreVersion).toHaveBeenCalledWith('post_01', 3);
    });

    it('keeps the Text and says why when a restore is refused', async () => {
      vi.mocked(postService.restoreVersion).mockRejectedValue(
        apiError(409, 'This Post is scheduled, so its Text is set.'),
      );
      renderPost(draft(THREE));
      const history = await openHistory();

      fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));

      expect(
        await panel('Draft').findByText('This Post is scheduled, so its Text is set.'),
      ).toBeInTheDocument();
      expect((await textCard()).getByText('the third text')).toBeInTheDocument();
      expect(track).not.toHaveBeenCalledWith('version_restored', expect.anything());
    });

    it('closes with Escape and with a click outside', async () => {
      renderPost(draft(THREE));

      const history = await openHistory();
      fireEvent.keyDown(history.getByRole('list'), { key: 'Escape' });
      await dialogClosed();
      expect(panel('Draft').getByRole('button', { name: 'History' })).toHaveFocus();

      await openHistory();
      fireEvent.pointerDown(document.body);
      await dialogClosed();
    });

    it('opens as a sheet on a phone, and restores from it', async () => {
      const matchMedia = vi.spyOn(window, 'matchMedia').mockImplementation(
        (query: string) =>
          ({
            matches: query === '(max-width: 639px)',
            media: query,
            addEventListener: () => {},
            removeEventListener: () => {},
          }) as unknown as MediaQueryList,
      );
      vi.mocked(postService.restoreVersion).mockResolvedValue(textOf(THREE[0]!));
      renderPost(draft(THREE));

      const history = await openHistory();
      fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));

      expect(await (await textCard()).findByText('the first text')).toBeInTheDocument();
      await dialogClosed();
      matchMedia.mockRestore();
    });

    it('is read-only on a Scheduled Post', async () => {
      renderPost(withScheduledPost(SCHEDULED));

      const history = await openHistory('Scheduled');

      expect(rows(history)).toHaveLength(2);
      expect(history.queryByRole('button', { name: /^Version/ })).not.toBeInTheDocument();
      expect(history.getByText('Version 1')).toBeInTheDocument();
    });

    it('is read-only on a Published Post', async () => {
      renderPost(withScheduledPost({ ...SCHEDULED, state: 'published', xPostUrl: null }));

      const history = await openHistory('Published');

      expect(history.queryByRole('button', { name: /^Version/ })).not.toBeInTheDocument();
      expect(history.getByText('Version 2')).toBeInTheDocument();
    });

    it('restores on a Failed Post', async () => {
      vi.mocked(postService.restoreVersion).mockResolvedValue(
        textOf(version(1, ['the final text'])),
      );
      renderPost(withScheduledPost({ ...SCHEDULED, state: 'failed', failedReason: 'Nope.' }));
      const history = await openHistory('Failed');

      fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));

      await waitFor(() => expect(postService.restoreVersion).toHaveBeenCalledWith('post_01', 1));
      expect(
        await panel('Failed').findByRole('button', { name: 'V1 · From your Brief' }),
      ).toBeInTheDocument();
    });
  });

  describe('Editing the Text', () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      vi.mocked(postService.saveText)
        .mockReset()
        .mockImplementation(async (_postId, texts) => ({
          format: texts.length > 1 ? 'thread' : 'post',
          parts: texts.map((text) => part(text)),
          versionNumber: 1,
          edited: true,
        }));
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    async function pause(ms = TEXT_SAVE_PAUSE_MS) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
    }

    it('edits a Draft in place, counting as the User types, and saves after a pause', async () => {
      renderPost(postWith('the final text'));
      const box = (await textCard()).getByRole('textbox', { name: 'Post text' });
      expect(box).toHaveValue('the final text');

      fireEvent.change(box, { target: { value: 'the final text, edited' } });

      expect((await textCard()).getByText('22 / 280')).toBeInTheDocument();
      expect(
        panel('Draft').getByRole('button', { name: 'V1 · From your Brief · edited' }),
      ).toBeInTheDocument();
      expect(postService.saveText).not.toHaveBeenCalled();
      await pause();
      expect(postService.saveText).toHaveBeenCalledTimes(1);
      expect(postService.saveText).toHaveBeenCalledWith('post_01', ['the final text, edited']);
    });

    it('saves a burst of typing once, and tracks it once', async () => {
      renderPost(postWith('the final text'));
      const box = (await textCard()).getByRole('textbox', { name: 'Post text' });

      fireEvent.change(box, { target: { value: 'the final text,' } });
      await pause(TEXT_SAVE_PAUSE_MS / 2);
      fireEvent.change(box, { target: { value: 'the final text, again' } });
      await pause();

      expect(postService.saveText).toHaveBeenCalledTimes(1);
      expect(postService.saveText).toHaveBeenCalledWith('post_01', ['the final text, again']);
      expect(vi.mocked(track).mock.calls.filter(([event]) => event === 'post_text_edited')).toEqual(
        [['post_text_edited', { format: 'post', part_count: 1 }]],
      );
    });

    it('edits each Part of a Thread, keeping its Parts in number and order', async () => {
      renderPost(threadWith([part('part one'), part('part two')]));
      const card = await textCard();

      fireEvent.change(card.getByRole('textbox', { name: 'Part 2 text' }), {
        target: { value: 'part two, edited' },
      });
      await pause();

      expect(postService.saveText).toHaveBeenCalledWith('post_01', [
        'part one',
        'part two, edited',
      ]);
      expect(card.getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2);
    });

    it('locks the Parts of a Failed Thread already live on X', async () => {
      renderPost(
        withVersions(
          withScheduledPost({
            ...SCHEDULED,
            state: 'failed',
            parts: [
              { text: 'Live one.', live: true, xPostUrl: 'https://x.com/i/web/status/1' },
              { text: 'Refused two.', live: false, xPostUrl: null },
            ],
          }),
          [version(1, ['Live one.', 'Refused two.']), version(2, ['Rewritten one.', 'New two.'])],
        ),
      );
      const card = await textCard();

      expect(card.queryByRole('textbox', { name: 'Part 1 text' })).not.toBeInTheDocument();
      fireEvent.change(card.getByRole('textbox', { name: 'Part 2 text' }), {
        target: { value: 'Fixed two.' },
      });
      await pause();

      expect(postService.saveText).toHaveBeenCalledWith('post_01', [
        'Rewritten one.',
        'Fixed two.',
      ]);
    });

    it('says an edit was not saved and retries it until it is', async () => {
      vi.mocked(postService.saveText)
        .mockRejectedValueOnce(new Error('Network Error'))
        .mockResolvedValueOnce({
          format: 'post',
          parts: [part('edited')],
          versionNumber: 1,
          edited: true,
        });
      renderPost(postWith('the final text'));
      const box = (await textCard()).getByRole('textbox', { name: 'Post text' });

      fireEvent.change(box, { target: { value: 'edited' } });
      await pause();

      expect(await panel('Draft').findByText('Edit not saved. Retrying.')).toBeInTheDocument();
      await pause(TEXT_SAVE_RETRY_MS);
      expect(postService.saveText).toHaveBeenCalledTimes(2);
      expect(vi.mocked(postService.saveText).mock.calls[1]).toEqual(['post_01', ['edited']]);
      expect(
        await panel('Draft').findByRole('button', { name: 'V1 · From your Brief · edited' }),
      ).toBeInTheDocument();
      expect(panel('Draft').queryByText('Edit not saved. Retrying.')).not.toBeInTheDocument();
    });

    it('says why an edit was refused, without retrying it', async () => {
      vi.mocked(postService.saveText).mockRejectedValue(
        apiError(409, 'This Post is scheduled, so its Text is set.'),
      );
      renderPost(postWith('the final text'));

      fireEvent.change((await textCard()).getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'edited' },
      });
      await pause();
      await pause(TEXT_SAVE_RETRY_MS * 4);

      expect(
        await panel('Draft').findByText(
          'Edit not saved. This Post is scheduled, so its Text is set.',
        ),
      ).toBeInTheDocument();
      expect(postService.saveText).toHaveBeenCalledTimes(1);
    });

    it('opens "Post to…" only once the edit is saved', async () => {
      let saved: () => void = () => {};
      vi.mocked(postService.saveText).mockImplementation(
        () =>
          new Promise((resolve) => {
            saved = () =>
              resolve({ format: 'post', parts: [part('edited')], versionNumber: 1, edited: true });
          }),
      );
      renderPost(postWith('the final text'));
      fireEvent.change((await textCard()).getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'edited' },
      });

      fireEvent.click(panel('Draft').getByRole('button', { name: 'Post to…' }));

      await waitFor(() => expect(postService.saveText).toHaveBeenCalledWith('post_01', ['edited']));
      expect(screen.queryByRole('dialog', { name: 'Post to…' })).not.toBeInTheDocument();
      expect(panel('Draft').getByRole('button', { name: 'Post to…' })).toHaveAttribute(
        'aria-busy',
        'true',
      );
      await act(async () => saved());
      expect(await screen.findByRole('dialog', { name: 'Post to…' })).toBeInTheDocument();
    });

    it('saves the edit before sending Feedback on it', async () => {
      vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['the second text']));
      renderPost(postWith('the final text'));
      fireEvent.change((await textCard()).getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'edited' },
      });
      fireEvent.change(panel('Draft').getByRole('textbox', { name: 'Feedback' }), {
        target: { value: 'shorter' },
      });

      fireEvent.click(panel('Draft').getByRole('button', { name: 'Send Feedback' }));

      expect(await (await textCard()).findByText('the second text')).toBeInTheDocument();
      expect(postService.saveText).toHaveBeenCalledWith('post_01', ['edited']);
      expect(vi.mocked(postService.saveText).mock.invocationCallOrder[0]).toBeLessThan(
        vi.mocked(postService.addVersion).mock.invocationCallOrder[0]!,
      );
      await pause();
      expect(postService.saveText).toHaveBeenCalledTimes(1);
    });

    it('drops an edit not yet saved when a Version is restored over it', async () => {
      const versions = [version(1, ['the first text']), version(2, ['the second text'])];
      vi.mocked(postService.restoreVersion).mockResolvedValue(textOf(versions[0]!));
      renderPost(draft(versions));
      fireEvent.change((await textCard()).getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'edited' },
      });

      fireEvent.click(panel('Draft').getByRole('button', { name: 'History' }));
      const history = within(await screen.findByRole('dialog', { name: 'History' }));
      fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));

      expect(
        await panel('Draft').findByRole('button', { name: 'V1 · From your Brief' }),
      ).toBeInTheDocument();
      expect((await textCard()).getByRole('textbox', { name: 'Post text' })).toHaveValue(
        'the first text',
      );
      await pause();
      expect(postService.saveText).not.toHaveBeenCalled();
    });

    it('shows a Scheduled and a Published Post read-only', async () => {
      const { unmount } = renderPost(withScheduledPost(SCHEDULED));
      expect((await textCard()).queryByRole('textbox')).not.toBeInTheDocument();
      unmount();

      renderPost(
        withScheduledPost({
          ...SCHEDULED,
          state: 'published',
          publishedAt: '2026-10-12T07:00:00Z',
          xPostUrl: 'https://x.com/i/web/status/1',
        }),
      );
      expect((await textCard()).queryByRole('textbox')).not.toBeInTheDocument();
    });

    it('shows the Text read-only to a User who is not Subscribed', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderPost(postWith('the final text'));

      const card = await textCard();
      expect(card.getByText('the final text')).toBeInTheDocument();
      expect(card.queryByRole('textbox')).not.toBeInTheDocument();
    });
  });

  describe('Draft', () => {
    const versionTwo = version(2, ['the second final'], { feedback: 'make it shorter' });

    function feedbackBox() {
      return panel('Draft').getByRole('textbox', { name: 'Feedback' });
    }

    /** Types `feedback` and sends it once the Subscription has loaded and sending is possible. */
    async function sendFeedback(feedback: string) {
      fireEvent.change(feedbackBox(), { target: { value: feedback } });
      const send = panel('Draft').getByRole('button', { name: 'Send Feedback' });
      await waitFor(() => expect(send).toBeEnabled());
      fireEvent.click(send);
    }

    it('offers a Feedback composer with the Format, a send arrow and "Post to…"', async () => {
      renderPost(postWith('the final text'));
      await textCard();

      const dock = panel('Draft');
      expect(feedbackBox()).toHaveAttribute('placeholder', 'What should change?');
      expect(dock.getByRole('radio', { name: 'Single post' })).toBeChecked();
      expect(dock.getByRole('button', { name: 'Send Feedback' })).toBeDisabled();
      expect(await dock.findByRole('button', { name: 'Post to…' })).toBeInTheDocument();
      expect(dock.queryByText(/everything you don.t mention/i)).not.toBeInTheDocument();
      expect(dock.queryByRole('button', { name: 'Rewrite' })).not.toBeInTheDocument();
    });

    it('writes the next Version from Feedback, locking the page, then shows it and empties the box', async () => {
      let answer: (v: Version) => void = () => {};
      vi.mocked(postService.addVersion).mockReturnValue(
        new Promise((resolve) => (answer = resolve)),
      );
      renderPost(postWith('the first final'));
      await textCard();

      await sendFeedback('  make it shorter ');

      const dock = panel('Draft');
      expect(feedbackBox()).toBeDisabled();
      expect(feedbackBox()).toHaveValue('  make it shorter ');
      expect(dock.getByRole('button', { name: 'Writing…' })).toBeDisabled();
      expect(dock.getByText('Writing Version 2 from your Feedback…')).toBeInTheDocument();
      expect(screen.getByRole('article', { name: 'Text' })).toHaveAttribute('aria-busy', 'true');
      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'make it shorter', 'post');
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'feedback' });

      answer(versionTwo);

      expect((await textCard()).getByText('the second final')).toBeInTheDocument();
      expect(
        await dock.findByRole('button', { name: 'V2 · From Feedback: “make it shorter”' }),
      ).toBeInTheDocument();
      expect(feedbackBox()).toHaveValue('');
      expect(feedbackBox()).toBeEnabled();
      expect(screen.getByRole('article', { name: 'Text' })).toHaveAttribute('aria-busy', 'false');
    });

    it("starts the Format on the Text's and switches it with the Feedback", async () => {
      vi.mocked(postService.addVersion).mockResolvedValue({
        ...versionTwo,
        format: 'thread',
        parts: [part('part one'), part('part two'), part('part three')],
      });
      renderPost(postWith('the first final'));
      await textCard();
      const format = () => within(panel('Draft').getByRole('radiogroup', { name: 'Format' }));
      expect(format().getByRole('radio', { name: 'Single post' })).toBeChecked();

      fireEvent.click(format().getByRole('radio', { name: 'Thread' }));
      await sendFeedback('expand it');

      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'expand it', 'thread');
      expect(
        await (await textCard()).findAllByRole('listitem', { name: /^Part \d of 3$/ }),
      ).toHaveLength(3);
      expect(format().getByRole('radio', { name: 'Thread' })).toBeChecked();
    });

    it('starts the Format on Thread when the Text is a Thread', async () => {
      renderPost(threadWith([part('the first part'), part('the second part')]));
      await textCard();

      const format = within(panel('Draft').getByRole('radiogroup', { name: 'Format' }));
      expect(format.getByRole('radio', { name: 'Thread' })).toBeChecked();
    });

    it('shows a failure in the dock with a way to try again, keeping the Feedback', async () => {
      vi.mocked(postService.addVersion)
        .mockRejectedValueOnce(apiError(502, 'Writing the Post failed. Please try again.'))
        .mockResolvedValueOnce(versionTwo);
      renderPost(postWith('the first final'));
      await textCard();

      await sendFeedback('make it shorter');

      const dock = panel('Draft');
      expect(await dock.findByRole('alert')).toHaveTextContent(
        'Writing the Post failed. Please try again.',
      );
      expect(feedbackBox()).toHaveValue('make it shorter');
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'feedback' });

      fireEvent.click(dock.getByRole('button', { name: 'Try again' }));

      expect(await (await textCard()).findByText('the second final')).toBeInTheDocument();
      expect(postService.addVersion).toHaveBeenLastCalledWith('post_01', 'make it shorter', 'post');
      expect(dock.queryByRole('alert')).not.toBeInTheDocument();
    });

    it.each([
      [404, 'Post not found.'],
      [409, 'This Post is scheduled, so it takes no Feedback.'],
    ])('does not count a refusal with a %i as a failed Version', async (status, detail) => {
      vi.mocked(postService.addVersion).mockRejectedValue(apiError(status, detail));
      renderPost(postWith('the first final'));
      await textCard();

      await sendFeedback('make it shorter');

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
      await textCard();

      await sendFeedback('make it shorter');

      expect(
        await panel('Draft').findByText(
          "You've made 30 attempts at a Version in the last hour. You can write again at 3:42 PM.",
        ),
      ).toHaveAttribute('role', 'status');
      expect(feedbackBox()).toHaveValue('make it shorter');
    });

    it('shows a length counter only near the Feedback limit, and refuses Feedback over it', async () => {
      renderPost(postWith('the first final'));
      await textCard();
      const dock = panel('Draft');

      fireEvent.change(feedbackBox(), { target: { value: 'a'.repeat(1000) } });
      expect(dock.queryByText(/100,000/)).not.toBeInTheDocument();

      fireEvent.change(feedbackBox(), { target: { value: '😀'.repeat(95_000) } });
      expect(dock.getByText('95,000 / 100,000 characters')).toBeInTheDocument();
      await waitFor(() =>
        expect(dock.getByRole('button', { name: 'Send Feedback' })).toBeEnabled(),
      );

      fireEvent.change(feedbackBox(), { target: { value: 'a'.repeat(100_003) } });
      expect(dock.getByText('3 characters over the 100,000 limit')).toBeInTheDocument();
      expect(dock.getByRole('button', { name: 'Send Feedback' })).toBeDisabled();
    });

    it('asks a User who is not Subscribed to subscribe in place of the send arrow', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderPost(postWith('the first final'));
      await textCard();

      const dock = panel('Draft');
      fireEvent.click(await dock.findByRole('link', { name: 'Subscribe to write' }));
      expect(dock.queryByRole('button', { name: 'Send Feedback' })).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('billing_choose_plan_opened', { source: 'post_feedback' });
    });

    it('keeps typed Feedback in the box after "Post to…"', async () => {
      renderPost(postWith('the first final'));
      await textCard();

      fireEvent.change(feedbackBox(), { target: { value: 'keep me' } });
      fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
      await dialogClosed();

      expect(feedbackBox()).toHaveValue('keep me');
    });
  });

  describe('Scheduled', () => {
    it('says when and where it goes out, with Edit and no Feedback', async () => {
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();

      const dock = panel('Scheduled');
      expect(dock.getByText('Scheduled for Mon, Oct 12, 9:00 AM')).toBeInTheDocument();
      expect(dock.getByText('Your profile')).toBeInTheDocument();
      expect(dock.getByRole('button', { name: /^V2 · From Feedback/ })).toBeInTheDocument();
      expect(await dock.findByRole('button', { name: 'Edit' })).toBeInTheDocument();
      expect(screen.queryByRole('textbox', { name: 'Feedback' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Post to…' })).not.toBeInTheDocument();
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
      await textCard();

      expect(panel('Scheduled').getByRole('link', { name: 'Indie makers' })).toHaveAttribute(
        'href',
        'https://x.com/i/communities/123',
      );
    });
  });

  describe('Scheduled: edit', () => {
    const COMMUNITY: Community = {
      id: '1493446837214187523',
      name: 'Indie makers',
      url: 'https://x.com/i/communities/1493446837214187523',
    };

    beforeEach(() => {
      vi.mocked(scheduledPostService.edit).mockReset();
      vi.mocked(scheduledPostService.cancel).mockReset();
      vi.mocked(scheduledPostService.pastCommunities).mockReset().mockResolvedValue([]);
      vi.mocked(scheduledPostService.lookUpCommunity).mockReset();
    });

    async function startEditing(scheduledPost: ScheduledPost = SCHEDULED) {
      renderPost(withScheduledPost(scheduledPost));
      await textCard();
      fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
      return within(await screen.findByRole('region', { name: 'Edit the Scheduled post' }));
    }

    it('turns the Parts into text boxes and saves the edited text', async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...SCHEDULED,
        parts: [{ text: 'the edited text', live: false, xPostUrl: null }],
      });
      const editor = await startEditing();

      const card = await textCard();
      const text = card.getByRole('textbox', { name: 'Post text' });
      expect(text).toHaveValue('the final text');
      fireEvent.change(text, { target: { value: 'the edited text' } });
      expect(card.getByText('15 / 280')).toBeInTheDocument();
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));

      await waitFor(() =>
        expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
          parts: ['the edited text'],
        }),
      );
      expect(await panel('Scheduled').findByRole('button', { name: 'Edit' })).toBeInTheDocument();
      expect((await textCard()).getByText('the edited text')).toBeInTheDocument();
      expect(screen.queryByRole('textbox', { name: 'Post text' })).not.toBeInTheDocument();
    });

    it('edits each Part of a Thread, keeping a Part already live on X as it is', async () => {
      const thread: ScheduledPost = {
        ...SCHEDULED,
        parts: [
          { text: 'Live one.', live: true, xPostUrl: 'https://x.com/i/web/status/1' },
          { text: 'Two.', live: false, xPostUrl: null },
        ],
      };
      vi.mocked(scheduledPostService.edit).mockResolvedValue(thread);
      const editor = await startEditing(thread);

      const card = await textCard();
      expect(card.queryByRole('textbox', { name: 'Part 1 text' })).not.toBeInTheDocument();
      expect(card.getByRole('link', { name: 'Part 1 is live on X' })).toBeInTheDocument();
      fireEvent.change(card.getByRole('textbox', { name: 'Part 2 text' }), {
        target: { value: 'Two, edited.' },
      });
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));

      await waitFor(() =>
        expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
          parts: ['Live one.', 'Two, edited.'],
        }),
      );
    });

    it('moves it to another time', async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...SCHEDULED,
        publishAt: '2026-10-13T08:30:00Z',
      });
      const editor = await startEditing();

      expect(editor.getByLabelText('Date')).toHaveValue('2026-10-12');
      expect(editor.getByLabelText('Time')).toHaveValue('09:00');
      fireEvent.change(editor.getByLabelText('Date'), { target: { value: '2026-10-13' } });
      fireEvent.change(editor.getByLabelText('Time'), { target: { value: '10:30' } });
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));

      await waitFor(() =>
        expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
          publishAt: '2026-10-13T08:30:00.000Z',
        }),
      );
      expect(
        await panel('Scheduled').findByText('Scheduled for Tue, Oct 13, 10:30 AM'),
      ).toBeInTheDocument();
    });

    it('moves it to a Community, shared with followers', async () => {
      vi.mocked(scheduledPostService.lookUpCommunity).mockResolvedValue(COMMUNITY);
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...SCHEDULED,
        community: COMMUNITY,
        shareWithFollowers: true,
      });
      const editor = await startEditing();

      fireEvent.click(editor.getByRole('radio', { name: 'Community' }));
      fireEvent.change(editor.getByLabelText('Community URL or ID'), {
        target: { value: COMMUNITY.url },
      });
      expect(await editor.findByRole('link', { name: 'Indie makers' })).toBeInTheDocument();
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));

      await waitFor(() =>
        expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
          community: { id: COMMUNITY.id, name: 'Indie makers' },
          shareWithFollowers: true,
        }),
      );
      expect(await panel('Scheduled').findByRole('link', { name: 'Indie makers' })).toHaveAttribute(
        'href',
        COMMUNITY.url,
      );
    });

    it('moves a Community post back to the profile', async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue(SCHEDULED);
      const editor = await startEditing({
        ...SCHEDULED,
        community: COMMUNITY,
        shareWithFollowers: true,
      });

      fireEvent.click(editor.getByRole('radio', { name: 'My profile' }));
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));

      await waitFor(() =>
        expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
          community: null,
        }),
      );
      expect(await panel('Scheduled').findByText('Your profile')).toBeInTheDocument();
    });

    it('throws the edits away on Cancel', async () => {
      const editor = await startEditing();

      fireEvent.change((await textCard()).getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'never mind' },
      });
      fireEvent.change(editor.getByLabelText('Time'), { target: { value: '11:00' } });
      fireEvent.click(editor.getByRole('button', { name: 'Cancel' }));

      expect(
        await panel('Scheduled').findByText('Scheduled for Mon, Oct 12, 9:00 AM'),
      ).toBeInTheDocument();
      expect((await textCard()).getByText('the final text')).toBeInTheDocument();
      expect(screen.queryByText('never mind')).not.toBeInTheDocument();
      expect(scheduledPostService.edit).not.toHaveBeenCalled();
    });

    it.each([
      'Part 1 is empty. Write something or remove it.',
      'Part 1 is 12 characters over the 280-character limit.',
      'Pick a time in the future.',
    ])('shows the API refusing the edit (%s) and stays in the editor', async (detail) => {
      vi.mocked(scheduledPostService.edit).mockRejectedValue(apiError(422, detail));
      const editor = await startEditing();

      fireEvent.change(editor.getByLabelText('Time'), { target: { value: '11:00' } });
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));

      expect(await editor.findByText(detail)).toBeInTheDocument();
      expect(editor.getByRole('button', { name: 'Save changes' })).toBeEnabled();
      expect((await textCard()).getByRole('textbox', { name: 'Post text' })).toBeInTheDocument();
    });

    it('says the save failed and to try again when the API gives no reason', async () => {
      vi.mocked(scheduledPostService.edit).mockRejectedValue(
        Object.assign(new Error('Network Error'), { isAxiosError: true }),
      );
      const editor = await startEditing();

      fireEvent.change((await textCard()).getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'the edited text' },
      });
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));

      expect(await editor.findByText("Couldn't save the changes. Try again.")).toBeInTheDocument();
      expect(editor.queryByText('Network Error')).not.toBeInTheDocument();
      expect((await textCard()).getByRole('textbox', { name: 'Post text' })).toHaveValue(
        'the edited text',
      );
      expect(editor.getByRole('button', { name: 'Save changes' })).toBeEnabled();
    });

    it('unschedules it, which makes the Post a Draft that takes Feedback again', async () => {
      vi.mocked(scheduledPostService.cancel).mockResolvedValue(undefined);
      const editor = await startEditing();
      vi.mocked(postService.list).mockClear();

      fireEvent.click(editor.getByRole('button', { name: 'Unschedule' }));

      await waitFor(() =>
        expect(scheduledPostService.cancel).toHaveBeenCalledWith('scheduled_post_01'),
      );
      expect(await panel('Draft').findByLabelText('Feedback')).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        'Posts / Drafts / the second text',
      );
      expect(screen.getByRole('link', { name: 'Drafts' })).toHaveAttribute('href', '/posts/drafts');
      expect(postService.list).toHaveBeenCalled();
    });

    it('shows why it could not be unscheduled', async () => {
      vi.mocked(scheduledPostService.cancel).mockRejectedValue(
        apiError(409, 'It is being published now, so it can no longer change.'),
      );
      const editor = await startEditing();

      fireEvent.click(editor.getByRole('button', { name: 'Unschedule' }));

      expect(
        await editor.findByText('It is being published now, so it can no longer change.'),
      ).toBeInTheDocument();
    });

    it('offers no Edit while it is being published', async () => {
      renderPost(withScheduledPost({ ...SCHEDULED, state: 'publishing' }));
      await textCard();

      expect(panel('Scheduled').queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    });

    it('sends a User who is not Subscribed to Choose a Plan instead of editing', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();

      fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));

      expect(await screen.findByRole('region', { name: 'Choose a Plan' })).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('billing_choose_plan_opened', {
        source: 'scheduled_post_edit',
      });
    });

    it('opens on the editor when it comes from Edit on the Posts page', async () => {
      vi.mocked(postService.get).mockResolvedValue(withScheduledPost(SCHEDULED));
      renderSignedIn('/posts/post_01', { state: { edit: true } });

      expect(
        await screen.findByRole('region', { name: 'Edit the Scheduled post' }),
      ).toBeInTheDocument();
      expect((await textCard()).getByRole('textbox', { name: 'Post text' })).toHaveValue(
        'the final text',
      );
    });

    it('clears the request to edit once the editor is open, so a reload shows the Post', async () => {
      vi.mocked(postService.get).mockResolvedValue(withScheduledPost(SCHEDULED));
      renderSignedIn('/posts/post_01', { state: { edit: true } });

      await screen.findByRole('region', { name: 'Edit the Scheduled post' });

      await waitFor(() =>
        expect(screen.getByRole('status', { name: 'Current state' })).toHaveTextContent('null'),
      );
      expect(screen.getByRole('status', { name: 'Current path' })).toHaveTextContent(
        '/posts/post_01',
      );
      expect(screen.getByRole('region', { name: 'Edit the Scheduled post' })).toBeInTheDocument();
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

    it('says when and where it was published, and links to it on X', async () => {
      renderPost(withScheduledPost(PUBLISHED));
      await textCard();

      const dock = panel('Published');
      expect(dock.getByText('Published Mon, Oct 12, 9:00 AM')).toBeInTheDocument();
      expect(dock.getByText('Your profile')).toBeInTheDocument();
      expect(dock.getByRole('button', { name: /^V2 · From Feedback/ })).toBeInTheDocument();
      expect(dock.getByRole('link', { name: 'View on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1890000000000000001',
      );
      expect(screen.queryByRole('textbox', { name: 'Feedback' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Post to…' })).not.toBeInTheDocument();
    });

    it('says whether a Community post was shared with followers', async () => {
      renderPost(
        withScheduledPost({
          ...PUBLISHED,
          community: { id: '123', name: null, url: 'https://x.com/i/communities/123' },
          shareWithFollowers: true,
        }),
      );
      await textCard();

      expect(panel('Published').getByText(/Shared with your followers/)).toBeInTheDocument();
      expect(panel('Published').getByRole('link', { name: '123' })).toBeInTheDocument();
    });
  });

  describe('Failed', () => {
    const FAILED: ScheduledPost = {
      ...SCHEDULED,
      state: 'failed',
      failedReason: 'X refused the post: duplicate content.',
    };

    it('shows when it was due and why in the dock, then takes Feedback', async () => {
      vi.mocked(postService.addVersion).mockResolvedValue(
        version(3, ['the third text'], { feedback: 'not a duplicate' }),
      );
      renderPost(withScheduledPost(FAILED));
      await textCard();

      const dock = panel('Failed');
      expect(
        dock.getByText('This Post didn’t go out. It was due Mon, Oct 12, 9:00 AM.'),
      ).toBeInTheDocument();
      expect(dock.getByText('X refused the post: duplicate content.')).toBeInTheDocument();
      expect(await dock.findByRole('button', { name: 'Post to…' })).toBeInTheDocument();
      fireEvent.change(dock.getByRole('textbox', { name: 'Feedback' }), {
        target: { value: 'not a duplicate' },
      });
      const send = dock.getByRole('button', { name: 'Send Feedback' });
      await waitFor(() => expect(send).toBeEnabled());
      fireEvent.click(send);

      expect(await (await textCard()).findByText('the third text')).toBeInTheDocument();
      expect(
        dock.getByRole('button', { name: 'V3 · From Feedback: “not a duplicate”' }),
      ).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts / Failed /');
    });

    it('marks the Parts of a Thread already live on X, with the Text after them', async () => {
      renderPost(
        withVersions(
          withScheduledPost({
            ...FAILED,
            parts: [
              { text: 'Live one.', live: true, xPostUrl: 'https://x.com/i/web/status/1' },
              { text: 'Refused two.', live: false, xPostUrl: null },
            ],
          }),
          [version(1, ['Live one.', 'Refused two.']), version(2, ['Rewritten one.', 'New two.'])],
        ),
      );

      const card = await textCard();
      const [first, second] = card
        .getAllByRole('listitem', { name: /^Part \d of 2$/ })
        .map((item) => within(item));
      expect(first!.getByText('Live one.')).toBeInTheDocument();
      expect(first!.getByRole('link', { name: 'Part 1 is live on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1',
      );
      expect(second!.getByText('New two.')).toBeInTheDocument();
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

    /** Opens "Post to…" on the Draft `post`, once its Version is on screen. */
    async function openPostTo(post: PostDetail = postWith('the final text')): Promise<Dialog> {
      renderPost(post);
      await textCard();
      fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));
      return within(await screen.findByRole('dialog', { name: 'Post to…' }));
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

    it('replaces Schedule and Post now with "Post to…"', async () => {
      renderPost(postWith('the final text'));
      await textCard();

      const draftPanel = panel('Draft');
      expect(await draftPanel.findByRole('button', { name: 'Post to…' })).toBeInTheDocument();
      expect(draftPanel.queryByRole('button', { name: 'Schedule' })).not.toBeInTheDocument();
      expect(draftPanel.queryByRole('button', { name: 'Post now' })).not.toBeInTheDocument();
    });

    it('names the Format, the Part count and the X account it posts as, and no Version', async () => {
      const dialog = await openPostTo(threadWith([part('the first part'), part('the second')]));

      expect(dialog.getByText('Thread · 2 Parts · as @ada')).toBeInTheDocument();
      expect(dialog.queryByText(/Version 1/)).not.toBeInTheDocument();
    });

    it("schedules the Post's Text to the User's profile for a day and time in their time zone", async () => {
      vi.mocked(scheduledPostService.schedule).mockResolvedValue(SCHEDULED);
      const dialog = await openPostTo();

      expect(dialog.getByRole('radio', { name: 'My profile' })).toBeChecked();
      scheduleAt(dialog, '2026-10-12', '09:00');
      expect(dialog.getByText('In your time zone, Europe/Rome.')).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Schedule for Mon, Oct 12, 9:00 AM' }));

      await dialogClosed();
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { postId: 'post_01' },
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
        { postId: 'post_01' },
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
        { postId: 'post_01' },
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
        { postId: 'post_01' },
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
        { postId: 'post_01' },
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
      await textCard();

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
      await textCard();

      fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));

      expect(await screen.findByRole('dialog', { name: 'Post to…' })).toBeInTheDocument();
    });
  });

  describe('Failed: Post to…', () => {
    const FAILED: ScheduledPost = {
      ...SCHEDULED,
      state: 'failed',
      failedReason: 'X refused the post: duplicate content.',
    };
    const COMMUNITY_ID = '1493446837214187523';
    const LIVE_ONE = { text: 'Live one.', live: true, xPostUrl: 'https://x.com/i/web/status/1' };
    /** A Thread whose Part 1 went out from Version 1 and whose Part 2 X refused. */
    const FAILED_PARTWAY: ScheduledPost = {
      ...FAILED,
      parts: [LIVE_ONE, { text: 'Refused two.', live: false, xPostUrl: null }],
      failedReason: 'X refused Part 2: Nope',
    };

    function failedThread(latest: Version): PostDetail {
      return withVersions(withScheduledPost(FAILED_PARTWAY), [
        version(1, ['Live one.', 'Refused two.']),
        latest,
      ]);
    }

    afterEach(() => {
      vi.useRealTimers();
    });

    beforeEach(() => {
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(new Date('2026-10-10T12:00'));
      vi.mocked(scheduledPostService.edit).mockReset();
      vi.mocked(scheduledPostService.schedule).mockReset();
      vi.mocked(scheduledPostService.postNow).mockReset();
      vi.mocked(scheduledPostService.pastCommunities).mockReset().mockResolvedValue([]);
    });

    /** Opens "Post to…" on the Failed `post` once it loads. */
    async function openRetry(post: PostDetail = withScheduledPost(FAILED)): Promise<Dialog> {
      renderPost(post);
      await textCard();
      fireEvent.click(await panel('Failed').findByRole('button', { name: 'Post to…' }));
      return within(await screen.findByRole('dialog', { name: 'Post to…' }));
    }

    it('shows the Text, from the latest Version, not the text that failed', async () => {
      renderPost(withScheduledPost(FAILED));

      expect((await textCard()).getByText('the second text')).toBeInTheDocument();
      expect(screen.queryByText('the final text')).not.toBeInTheDocument();
    });

    it("reschedules the Failed one with the Post's Text", async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...SCHEDULED,
        parts: [{ text: 'the second text', live: false, xPostUrl: null }],
      });
      const dialog = await openRetry();

      expect(dialog.getByText('Single post · 1 Part · as @ada')).toBeInTheDocument();
      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: 'Schedule for Mon, Oct 12, 9:00 AM' }));

      await dialogClosed();
      expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
        copyText: true,
        community: null,
        shareWithFollowers: false,
        publishAt: '2026-10-12T07:00:00.000Z',
      });
      expect(scheduledPostService.schedule).not.toHaveBeenCalled();
      expect(
        panel('Scheduled').getByText('Scheduled for Mon, Oct 12, 9:00 AM'),
      ).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts / Scheduled /');
    });

    it("posts the Post's Text now and shows the Published Post", async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...SCHEDULED,
        state: 'published',
        publishedAt: '2026-10-10T12:00:14Z',
        xPostUrl: 'https://x.com/i/web/status/1890000000000000002',
        parts: [{ text: 'the second text', live: true, xPostUrl: 'https://x.com/i/web/status/2' }],
      });
      const dialog = await openRetry();

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      expect(dialog.getByText('the second text')).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await dialogClosed();
      expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
        copyText: true,
        community: null,
        shareWithFollowers: false,
        publishNow: true,
      });
      expect(panel('Published').getByRole('link', { name: 'View on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1890000000000000002',
      );
    });

    it("copies the Post's Text even when it is the text that failed", async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue(SCHEDULED);
      renderPost(withVersions(withScheduledPost(FAILED), [version(1, ['the final text'])]));
      await textCard();

      fireEvent.click(await panel('Failed').findByRole('button', { name: 'Post to…' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      await dialogClosed();
      expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
        copyText: true,
        community: null,
        shareWithFollowers: false,
        publishAt: '2026-10-12T07:00:00.000Z',
      });
    });

    it('starts on the Community the Failed one was for', async () => {
      const dialog = await openRetry(
        withScheduledPost({
          ...FAILED,
          community: {
            id: COMMUNITY_ID,
            name: 'Build in Public',
            url: `https://x.com/i/communities/${COMMUNITY_ID}`,
          },
          shareWithFollowers: false,
        }),
      );

      expect(dialog.getByRole('radio', { name: 'Community' })).toBeChecked();
      expect(dialog.getByLabelText('Community URL or ID')).toHaveValue(
        `https://x.com/i/communities/${COMMUNITY_ID}`,
      );
      expect(dialog.getByRole('checkbox', { name: 'Also share with followers' })).not.toBeChecked();
    });

    it('shows the live Parts of a Thread first and locked, and sends only the rest', async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...FAILED_PARTWAY,
        state: 'published',
        xPostUrl: 'https://x.com/i/web/status/1',
        parts: [
          LIVE_ONE,
          { text: 'Fixed two.', live: true, xPostUrl: 'https://x.com/i/web/status/3' },
          { text: 'New three.', live: true, xPostUrl: 'https://x.com/i/web/status/4' },
        ],
      });
      const dialog = await openRetry(
        failedThread(version(2, ['Rewritten one.', 'Fixed two.', 'New three.'])),
      );

      expect(dialog.getByText('Thread · 3 Parts · as @ada')).toBeInTheDocument();
      expect(
        dialog.getByText('Part 1 is already on X, so only Parts 2 to 3 go out, as replies to it.'),
      ).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));

      expect(dialog.getByText(/These 2 Parts go out/)).toBeInTheDocument();
      const [first, second, third] = within(dialog.getByRole('list', { name: 'Parts' }))
        .getAllByRole('listitem')
        .map((item) => within(item));
      expect(first!.getByText('Live one.')).toBeInTheDocument();
      expect(first!.getByRole('link', { name: 'Part 1 is live on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1',
      );
      expect(first!.getByText('Already on X, so it can’t change.')).toBeInTheDocument();
      expect(first!.queryByText(/\/ 280/)).not.toBeInTheDocument();
      expect(dialog.queryByText('Rewritten one.')).not.toBeInTheDocument();
      expect(second!.getByText('Fixed two.')).toBeInTheDocument();
      expect(second!.getByText('10 / 280')).toBeInTheDocument();
      expect(third!.getByText('New three.')).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await dialogClosed();
      expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
        copyText: true,
        community: null,
        shareWithFollowers: false,
        publishNow: true,
      });
      expect(panel('Published')).toBeTruthy();
    });

    it('refuses a Text with no Part after the live ones', async () => {
      const dialog = await openRetry(failedThread(version(2, ['Just one now.'])));

      expect(
        dialog.getByText(
          'Part 1 is already on X, and the text has no Part after it. Ask for more Parts with Feedback.',
        ),
      ).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Review and post' })).toBeDisabled();
    });

    it('does not count a live Part against the limit', async () => {
      const longLive = { ...LIVE_ONE, text: 'a'.repeat(300) };
      const dialog = await openRetry(
        withVersions(
          withScheduledPost({ ...FAILED_PARTWAY, parts: [longLive, FAILED_PARTWAY.parts[1]!] }),
          [version(1, [longLive.text, 'Refused two.']), version(2, ['x', 'Fixed two.'])],
        ),
      );

      expect(dialog.queryByText(/over X's/)).not.toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Review and post' })).toBeEnabled();
    });

    it('shows why the retry was refused and keeps the dialog open', async () => {
      vi.mocked(scheduledPostService.edit).mockRejectedValue(
        apiError(409, 'Publishing has started, so this Scheduled post can no longer change.'),
      );
      const dialog = await openRetry();

      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      expect(
        await dialog.findByText(
          'Publishing has started, so this Scheduled post can no longer change.',
        ),
      ).toBeInTheDocument();
    });

    it('sends a User who is no longer Subscribed to Choose a Plan', async () => {
      vi.mocked(scheduledPostService.edit).mockRejectedValue(apiError(403, 'Subscribe first.'));
      const dialog = await openRetry();
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      expect(await screen.findByRole('region', { name: 'Choose a Plan' })).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('billing_choose_plan_opened', { source: 'post_to' });
    });
  });

  // Whatever sends the Post out on this page passes its answer to usePost's setScheduledPost.
  it("updates the sidebar's Failed badge once the Post's Scheduled post Fails", async () => {
    vi.mocked(scheduledPostService.postNow).mockResolvedValue({
      ...SCHEDULED,
      state: 'failed',
      failedReason: 'X refused the post: duplicate content.',
    });
    renderPost(postWith('the final text'));
    await textCard();
    const sidebar = within(screen.getByRole('navigation', { name: 'Main' }));
    expect(sidebar.getByRole('link', { name: 'Posts' })).toBeInTheDocument();
    vi.mocked(postService.list).mockResolvedValue({
      ...NO_POSTS,
      counts: { ...NO_POSTS.counts, failed: 1 },
    });

    fireEvent.click(await panel('Draft').findByRole('button', { name: 'Post to…' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

    expect(await sidebar.findByRole('link', { name: 'Posts, 1 Failed' })).toBeInTheDocument();
  });

  it("clears the sidebar's Failed badge once a Failed Post is retried", async () => {
    vi.mocked(postService.list).mockResolvedValue({
      ...NO_POSTS,
      counts: { ...NO_POSTS.counts, failed: 1 },
    });
    vi.mocked(scheduledPostService.edit).mockResolvedValue({
      ...SCHEDULED,
      state: 'published',
      publishedAt: '2026-10-10T12:00:14Z',
      xPostUrl: 'https://x.com/i/web/status/1890000000000000002',
    });
    renderPost(
      withScheduledPost({
        ...SCHEDULED,
        state: 'failed',
        failedReason: 'X refused the post: duplicate content.',
      }),
    );
    await textCard();
    const sidebar = within(screen.getByRole('navigation', { name: 'Main' }));
    expect(await sidebar.findByRole('link', { name: 'Posts, 1 Failed' })).toBeInTheDocument();
    vi.mocked(postService.list).mockResolvedValue(NO_POSTS);

    fireEvent.click(await panel('Failed').findByRole('button', { name: 'Post to…' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

    expect(await sidebar.findByRole('link', { name: 'Posts' })).toBeInTheDocument();
    expect(sidebar.queryByRole('link', { name: 'Posts, 1 Failed' })).not.toBeInTheDocument();
  });
});
