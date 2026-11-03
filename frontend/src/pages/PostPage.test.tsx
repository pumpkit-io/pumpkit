import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
  type BoundFunctions,
  type queries,
} from '@testing-library/react';
import { CanceledError } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

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
vi.mock('@/services/mediaService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/mediaService')>()),
  mediaService: {
    attach: vi.fn(),
    remove: vi.fn(),
    attachToScheduledPost: vi.fn(),
    removeFromScheduledPost: vi.fn(),
    setAltText: vi.fn(),
    setScheduledPostAltText: vi.fn(),
    preview: vi.fn(),
  },
}));
vi.mock('@/features/posts/media/videoFile', () => ({ readVideo: vi.fn() }));
vi.mock('@/services/usageService', () => ({
  usageService: { get: vi.fn() },
}));
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn().mockResolvedValue('paywall') },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import type { Instance } from '@/lib/instance';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { TEXT_SAVE_PAUSE_MS, TEXT_SAVE_RETRY_MS } from '@/features/posts/text/textSaver';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import {
  postService,
  textOf,
  type Part,
  type PostDetail,
  type PostText,
  type Version,
} from '@/services/postService';
import {
  scheduledPostService,
  type Community,
  type ScheduledPost,
  type ScheduledPostPart,
} from '@/services/scheduledPostService';
import { mediaService, type Media } from '@/services/mediaService';
import { readVideo } from '@/features/posts/media/videoFile';
import { usageService, type Usage } from '@/services/usageService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import { xConnectionReturn } from '@/features/xConnection/xConnectionReturn';
import {
  LEVELSIO,
  NOT_SUBSCRIBED,
  NO_POSTS,
  PAULG,
  SUBSCRIBED,
  allowanceUsedUp,
  apiError,
  renderSignedIn,
  currentPath,
  usageWith,
} from './testing/signedInApp';

const CONNECTED: XConnection = {
  handle: 'ada',
  charLimit: 280,
  premium: false,
  needsReconnect: false,
  needsReconnectForMedia: false,
  scheduledPostsWaiting: 0,
  photoUrl: null,
  offerPhoto: false,
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
      textMedia: [],
    },
    versions,
  );
}

function postWith(final: string, finalCharCount = final.length): PostDetail {
  return draft([version(1, [final], { parts: [part(final, finalCharCount)] })]);
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
  parts: [{ text: 'the final text', live: false, xPostUrl: null, media: [] }],
  state: 'scheduled',
  publishAt: '2026-10-12T07:00:00Z',
  publishedAt: null,
  xPostUrl: null,
  failedReason: null,
  community: null,
  shareWithFollowers: false,
  createdAt: '2026-10-10T12:00:00Z',
  posting: false,
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

/** The Post's card, which holds the origin line, undo, redo, History and "Post to…". */
function card() {
  return within(screen.getByRole('article', { name: 'Text' }));
}

function panel(name: string) {
  return within(screen.getByRole('region', { name }));
}

/** "Posting…" in the Post page's live region, there before any dock, so the change is announced. */
function announcedPosting() {
  return screen.queryByText('Posting…', { selector: '[role="status"] > span' });
}

/** The Post page's one sr-only live region. */
function liveRegion() {
  return screen
    .getAllByRole('status')
    .find((element) => element.tagName === 'P' && element.classList.contains('sr-only'));
}

const EDIT_CLOSED = "Posting started while you were editing, so your changes weren't saved.";

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
    vi.mocked(usageService.get).mockReset().mockResolvedValue({ allowance: null });
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
      (await screen.findByRole('link', { name: 'Writing in the style of @levelsio' })).closest(
        'header',
      ),
    ).not.toBeNull();
  });

  it("shows the Persona's photos in the header and their handles on focus", async () => {
    vi.mocked(inspirationAuthorService.list).mockResolvedValue([
      { ...LEVELSIO, photoUrl: 'https://pbs.twimg.com/levelsio_normal.jpg' },
      PAULG,
    ]);
    renderPost(postWith('the final text'));

    const chip = await screen.findByRole('link', {
      name: 'Writing in the style of @levelsio, @paulg',
    });
    expect(chip).toHaveAttribute('href', '/persona');
    expect(chip.querySelector('img')).toHaveAttribute(
      'src',
      'https://pbs.twimg.com/levelsio_normal.jpg',
    );
    expect(within(chip).getByText('P')).toBeInTheDocument();
    expect(within(chip).getByText('@paulg')).not.toBeVisible();

    act(() => chip.focus());

    expect(within(chip).getByText('@levelsio')).toBeVisible();
    expect(within(chip).getByText('@paulg')).toBeVisible();
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

    expect(await screen.findByRole('status', { name: 'Loading the post' })).toBeInTheDocument();
    expect(screen.queryByRole('article', { name: 'Text' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Feedback' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send feedback' })).toBeDisabled();
  });

  it('says so when the Post is not found', async () => {
    vi.mocked(postService.get).mockRejectedValue(apiError(404, 'Post not found.'));
    renderSignedIn('/posts/post_missing');

    expect(await screen.findByText(/this post isn.t here/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Write a new post' })).toHaveAttribute('href', '/new');
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

    it("shows the X account's photo where it shows the X account", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...CONNECTED,
        photoUrl: 'https://pbs.twimg.com/ada_200x200.jpg',
      });
      renderPost(postWith('the final text'));

      const only = (await screen.findByRole('article', { name: 'Text' })).querySelector('li')!;
      await within(only).findByText('@ada');
      expect(only.querySelector('img')).toHaveAttribute(
        'src',
        'https://pbs.twimg.com/ada_200x200.jpg',
      );
    });

    it("hides the User's initials once the X account's photo has loaded", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...CONNECTED,
        photoUrl: 'https://pbs.twimg.com/ada_200x200.jpg',
      });
      renderPost(postWith('the final text'));

      const only = (await screen.findByRole('article', { name: 'Text' })).querySelector('li')!;
      await within(only).findByText('@ada');
      expect(within(only).getByText('AL')).toBeInTheDocument();
      fireEvent.load(only.querySelector('img')!);

      expect(within(only).queryByText('AL')).not.toBeInTheDocument();
    });

    it("shows the User's initials when the X account's photo fails to load", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({
        ...CONNECTED,
        photoUrl: 'https://pbs.twimg.com/gone.jpg',
      });
      renderPost(postWith('the final text'));

      const only = (await screen.findByRole('article', { name: 'Text' })).querySelector('li')!;
      await within(only).findByText('@ada');
      fireEvent.error(only.querySelector('img')!);

      expect(only.querySelector('img')).toBeNull();
      expect(within(only).getByText('AL')).toBeInTheDocument();
    });

    it('shows a single post with no Version number, Format, Part count or place', async () => {
      renderPost(postWith('the final text'));

      const card = await textCard();
      const only = card.getByRole('listitem', { name: 'Post' });
      expect(within(only).getByText('14 / 280')).toBeInTheDocument();
      expect(within(only).queryByText('1/1')).not.toBeInTheDocument();
      expect(card.queryByText(/version 1/i)).not.toBeInTheDocument();
      expect(card.queryByText(/Single post|1 part/i)).not.toBeInTheDocument();
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
          parts: [{ text: 'the final text, edited', live: false, xPostUrl: null, media: [] }],
        }),
      );

      const card = await textCard();
      expect(card.getByText('the final text, edited')).toBeInTheDocument();
      expect(card.getByText('22 / 280')).toBeInTheDocument();
    });

    it.each([
      ['History', 'Versions history'],
      ['Copy post', 'Copy post'],
    ])('labels %s on hover', async (button, label) => {
      renderPost(postWith('the final text'));
      const card = await textCard();

      fireEvent.pointerMove(card.getByRole('button', { name: button }), { pointerType: 'mouse' });

      expect(await screen.findByRole('tooltip')).toHaveTextContent(label);
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
          parts: [{ text: 'the final text, edited', live: false, xPostUrl: null, media: [] }],
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

      fireEvent.click(card().getByRole('button', { name: 'V1 · From your brief' }));

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
        card().getByRole('button', {
          name: 'V2 · From feedback: “Shorter, and drop the last line.”',
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
        card().getByRole('button', { name: 'V1 · From your brief · edited' }),
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

    async function openHistory() {
      await textCard();
      fireEvent.click(card().getByRole('button', { name: 'History' }));
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

      const expand = history.getByRole('button', { name: 'Show the full feedback of version 3' });
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
        card().getByRole('button', { name: 'V2 · From feedback: “Punchier hook”' }),
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
      expect(card().getByRole('button', { name: 'History' })).toHaveFocus();

      await openHistory();
      fireEvent.pointerDown(document.body);
      await dialogClosed();
    });

    it('keeps its hover label shut while open, and when focus comes back on close', async () => {
      renderPost(draft(THREE));

      const history = await openHistory();
      fireEvent.pointerMove(card().getByRole('button', { name: 'History' }), {
        pointerType: 'mouse',
      });
      fireEvent.keyDown(history.getByRole('list'), { key: 'Escape' });
      await dialogClosed();

      expect(card().getByRole('button', { name: 'History' })).toHaveFocus();
      await act(() => new Promise((resolve) => setTimeout(resolve, 300)));
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
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

      const history = await openHistory();

      expect(rows(history)).toHaveLength(2);
      expect(history.queryByRole('button', { name: /^Version/ })).not.toBeInTheDocument();
      expect(history.getByText('Version 1')).toBeInTheDocument();
    });

    it('is read-only on a Published Post', async () => {
      renderPost(withScheduledPost({ ...SCHEDULED, state: 'published', xPostUrl: null }));

      const history = await openHistory();

      expect(history.queryByRole('button', { name: /^Version/ })).not.toBeInTheDocument();
      expect(history.getByText('Version 2')).toBeInTheDocument();
    });

    it('restores on a Failed Post', async () => {
      vi.mocked(postService.restoreVersion).mockResolvedValue(
        textOf(version(1, ['the final text'])),
      );
      renderPost(withScheduledPost({ ...SCHEDULED, state: 'failed', failedReason: 'Nope.' }));
      const history = await openHistory();

      fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));

      await waitFor(() => expect(postService.restoreVersion).toHaveBeenCalledWith('post_01', 1));
      expect(
        await card().findByRole('button', { name: 'V1 · From your brief' }),
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
        card().getByRole('button', { name: 'V1 · From your brief · edited' }),
      ).toBeInTheDocument();
      expect(postService.saveText).not.toHaveBeenCalled();
      await pause();
      expect(postService.saveText).toHaveBeenCalledTimes(1);
      expect(postService.saveText).toHaveBeenCalledWith('post_01', ['the final text, edited']);
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
              {
                text: 'Live one.',
                live: true,
                xPostUrl: 'https://x.com/i/web/status/1',
                media: [],
              },
              { text: 'Refused two.', live: false, xPostUrl: null, media: [] },
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

      expect(await card().findByText('Edit not saved. Retrying.')).toBeInTheDocument();
      await pause(TEXT_SAVE_RETRY_MS);
      expect(postService.saveText).toHaveBeenCalledTimes(2);
      expect(vi.mocked(postService.saveText).mock.calls[1]).toEqual(['post_01', ['edited']]);
      expect(
        await card().findByRole('button', { name: 'V1 · From your brief · edited' }),
      ).toBeInTheDocument();
      expect(card().queryByText('Edit not saved. Retrying.')).not.toBeInTheDocument();
    });

    it('saves an edit still in its pause when the page closes', async () => {
      const { unmount } = renderPost(postWith('the final text'));
      fireEvent.change((await textCard()).getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'edited' },
      });

      unmount();

      expect(postService.saveText).toHaveBeenCalledWith('post_01', ['edited']);
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

      fireEvent.click(card().getByRole('button', { name: 'Post to…' }));

      await waitFor(() => expect(postService.saveText).toHaveBeenCalledWith('post_01', ['edited']));
      expect(screen.queryByRole('dialog', { name: 'Post to…' })).not.toBeInTheDocument();
      expect(card().getByRole('button', { name: 'Post to…' })).toHaveAttribute('aria-busy', 'true');
      await act(async () => saved());
      expect(await screen.findByRole('dialog', { name: 'Post to…' })).toBeInTheDocument();
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
  });

  describe('Media', () => {
    const MB = 1024 * 1024;

    function image(id: string): Media {
      return {
        id,
        kind: 'image',
        previewUrl: `/media/${id}/preview`,
        width: 40,
        height: 30,
        altText: null,
        durationMs: null,
      };
    }

    function withMedia(post: PostDetail, textMedia: Media[][]): PostDetail {
      return { ...post, textMedia };
    }

    function photo(name = 'photo.png', type = 'image/png', size = 1024): File {
      return new File([new Uint8Array(size)], name, { type });
    }

    function chooseFiles(part: string, ...files: File[]) {
      fireEvent.change(screen.getByLabelText(`Choose media for ${part}`), { target: { files } });
    }

    function mediaOn(part: string) {
      return within(screen.getByRole('list', { name: `Media on ${part}` }));
    }

    function threadOfTwo(): PostDetail {
      return threadWith([part('one'), part('two')]);
    }

    beforeEach(() => {
      vi.mocked(mediaService.attach).mockReset();
      vi.mocked(mediaService.remove).mockReset().mockResolvedValue();
      vi.mocked(mediaService.preview)
        .mockReset()
        .mockImplementation(async (url) => new Blob([url], { type: 'image/webp' }));
      let made = 0;
      URL.createObjectURL = vi.fn(() => `blob:local-${++made}`);
      URL.revokeObjectURL = vi.fn();
    });

    it('puts a media button on each Part of the Text, named for its Part, and none in the dock', async () => {
      renderPost(threadOfTwo());
      await textCard();

      const one = card().getByRole('listitem', { name: 'Part 1 of 2' });
      const two = card().getByRole('listitem', { name: 'Part 2 of 2' });
      expect(within(one).getByRole('button', { name: 'Add media to Part 1' })).toBeInTheDocument();
      expect(within(two).getByRole('button', { name: 'Add media to Part 2' })).toBeInTheDocument();
      expect(panel('Draft').queryByRole('button', { name: /media/i })).not.toBeInTheDocument();
      expect(panel('Draft').queryByLabelText(/choose media/i)).not.toBeInTheDocument();
    });

    it('names the button for the post when the Text is a single post', async () => {
      renderPost(postWith('the final text'));
      await textCard();

      expect(card().getByRole('button', { name: 'Add media to the post' })).toBeInTheDocument();
    });

    it('shows a chosen image uploading with its progress, then its stored preview', async () => {
      let progress: (sent: number, bytesLeft: number) => void = () => {};
      let answer: (media: Media) => void = () => {};
      vi.mocked(mediaService.attach).mockImplementation((_post, _part, _file, options) => {
        progress = options?.onProgress ?? progress;
        return new Promise((resolve) => (answer = resolve));
      });
      renderPost(threadOfTwo());
      await textCard();
      const file = photo();

      chooseFiles('Part 2', file);

      const tile = await mediaOn('Part 2').findByRole('listitem', { name: 'Image 1' });
      expect(tile.querySelector('img')).toHaveAttribute('src', 'blob:local-1');
      const bar = within(tile).getByRole('progressbar', { name: 'Uploading image 1' });
      expect(mediaService.attach).toHaveBeenCalledWith('post_01', 2, file, expect.anything());

      act(() => progress(0.5, 1024));
      expect(bar).toHaveAttribute('aria-valuenow', '50');

      await act(async () => answer(image('media_01')));

      expect(within(tile).queryByRole('progressbar')).not.toBeInTheDocument();
      await waitFor(() =>
        expect(mediaService.preview).toHaveBeenCalledWith(
          '/media/media_01/preview',
          expect.anything(),
        ),
      );
      expect(track).toHaveBeenCalledWith('media_attached', {
        kind: 'image',
        via: 'button',
        on: 'text',
        source: 'web',
      });
    });

    it("shows the Text's Media from the server, read with the session", async () => {
      renderPost(withMedia(threadOfTwo(), [[], [image('media_01'), image('media_02')]]));
      await textCard();

      const tiles = mediaOn('Part 2').getAllByRole('listitem');
      expect(tiles.map((t) => t.getAttribute('aria-label'))).toEqual(['Image 1', 'Image 2']);
      expect(screen.queryByRole('list', { name: 'Media on Part 1' })).not.toBeInTheDocument();
      await waitFor(() =>
        expect(tiles[0]!.querySelector('img')).toHaveAttribute('src', 'blob:local-1'),
      );
      expect(mediaService.preview).toHaveBeenCalledWith(
        '/media/media_01/preview',
        expect.anything(),
      );
    });

    it('shows a muted block with an image icon when a preview fails to load', async () => {
      vi.mocked(mediaService.preview).mockRejectedValue(new Error('Network Error'));
      renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
      await textCard();

      const tile = mediaOn('the post').getByRole('listitem', { name: 'Image 1' });
      expect(await within(tile).findByText("Preview didn't load")).toBeInTheDocument();
    });

    it('removes an image with its ×', async () => {
      renderPost(withMedia(postWith('the final text'), [[image('media_01'), image('media_02')]]));
      await textCard();

      fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove image 1' }));

      await waitFor(() => expect(mediaOn('the post').getAllByRole('listitem')).toHaveLength(1));
      expect(mediaService.remove).toHaveBeenCalledWith('post_01', 'media_01');
      expect(track).toHaveBeenCalledWith('media_removed', {
        kind: 'image',
        on: 'text',
        source: 'web',
      });
    });

    it('puts a removed image back when the server keeps it', async () => {
      vi.mocked(mediaService.remove).mockRejectedValue(new Error('Network Error'));
      renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
      await textCard();

      fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove image 1' }));

      await waitFor(() => expect(mediaService.remove).toHaveBeenCalled());
      expect(await mediaOn('the post').findByRole('listitem', { name: 'Image 1' })).toBeTruthy();
    });

    it('takes an image off when the server already had', async () => {
      vi.mocked(mediaService.remove).mockRejectedValue(apiError(404, 'No such media.'));
      renderPost(withMedia(postWith('the final text'), [[image('media_01'), image('media_02')]]));
      await textCard();

      fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove image 1' }));

      await waitFor(() => expect(mediaOn('the post').getAllByRole('listitem')).toHaveLength(1));
      expect(screen.queryByText(/Couldn.t remove the image/)).not.toBeInTheDocument();
    });

    it("refuses a file over 5 MB or of a type X won't take on its tile, without sending it", async () => {
      renderPost(postWith('the final text'));
      await textCard();

      chooseFiles(
        'the post',
        photo('big.png', 'image/png', 5 * MB + 1),
        photo('clip.avi', 'video/x-msvideo'),
        photo('photo.heic', 'image/heic'),
      );

      const big = within(await mediaOn('the post').findByRole('listitem', { name: 'big.png' }));
      const clip = within(mediaOn('the post').getByRole('listitem', { name: 'clip.avi' }));
      const heic = within(mediaOn('the post').getByRole('listitem', { name: 'photo.heic' }));
      expect(big.getByText('Larger than 5 MB')).toBeInTheDocument();
      expect(clip.getByText('MP4 or MOV only')).toBeInTheDocument();
      expect(heic.getByText('JPEG, PNG, WEBP or GIF only')).toBeInTheDocument();
      const refused = mediaOn('the post');
      expect(refused.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
      expect(mediaService.attach).not.toHaveBeenCalled();

      fireEvent.click(refused.getByRole('button', { name: 'Remove big.png' }));

      expect(refused.queryByText('Larger than 5 MB')).not.toBeInTheDocument();
    });

    it("names the server's refusal, and offers Retry when the upload itself failed", async () => {
      vi.mocked(mediaService.attach)
        .mockRejectedValueOnce(
          apiError(422, "This image can't be read.", { code: 'MEDIA_UNREADABLE' }),
        )
        .mockRejectedValueOnce(new Error('Network Error'))
        .mockResolvedValueOnce(image('media_02'));
      renderPost(postWith('the final text'));
      await textCard();

      chooseFiles('the post', photo('broken.png'));
      const broken = within(
        await mediaOn('the post').findByRole('listitem', { name: 'broken.png' }),
      );
      expect(await broken.findByText("Can't read this image")).toBeInTheDocument();
      expect(broken.queryByRole('button', { name: 'Retry broken.png' })).not.toBeInTheDocument();

      chooseFiles('the post', photo('flaky.png'));
      fireEvent.click(await mediaOn('the post').findByRole('button', { name: 'Retry flaky.png' }));

      expect(await mediaOn('the post').findByRole('listitem', { name: 'Image 1' })).toBeTruthy();
      expect(mediaService.attach).toHaveBeenCalledTimes(3);
    });

    it("stops taking files once a Part holds four images, naming X's rule", async () => {
      const four = [1, 2, 3, 4].map((n) => image(`media_0${n}`));
      renderPost(withMedia(threadOfTwo(), [four, []]));
      await textCard();

      const button = card().getByRole('button', { name: 'Add media to Part 1' });
      expect(button).toHaveAttribute('aria-disabled', 'true');
      act(() => button.focus());
      expect(
        (await screen.findAllByText('X takes up to 4 images, or 1 GIF, or 1 video, per post'))[0],
      ).toBeInTheDocument();

      fireEvent.drop(card().getByRole('listitem', { name: 'Part 1 of 2' }), {
        dataTransfer: { files: [photo('fifth.png')], types: ['Files'] },
      });

      const fifth = within(await mediaOn('Part 1').findByRole('listitem', { name: 'fifth.png' }));
      expect(
        fifth.getByText('X takes up to 4 images, or 1 GIF, or 1 video, per post'),
      ).toBeInTheDocument();
      expect(mediaService.attach).not.toHaveBeenCalled();
    });

    it('offers no Retry on a failed upload while its Part is full', async () => {
      vi.mocked(mediaService.attach).mockRejectedValueOnce(new Error('Network Error'));
      const three = [1, 2, 3].map((n) => image(`media_0${n}`));
      renderPost(withMedia(postWith('the final text'), [three]));
      await textCard();

      chooseFiles('the post', photo('flaky.png'));
      expect(
        await mediaOn('the post').findByRole('button', { name: 'Retry flaky.png' }),
      ).toBeInTheDocument();
      vi.mocked(mediaService.attach).mockResolvedValueOnce(image('media_04'));
      chooseFiles('the post', photo('fourth.png'));

      expect(await mediaOn('the post').findByRole('listitem', { name: 'Image 4' })).toBeTruthy();
      expect(
        mediaOn('the post').queryByRole('button', { name: 'Retry flaky.png' }),
      ).not.toBeInTheDocument();
      expect(mediaOn('the post').getByText('Upload failed. Try again.')).toBeInTheDocument();
    });

    it('asks before following a link away while an image uploads', async () => {
      vi.mocked(mediaService.attach).mockReturnValue(new Promise(() => {}));
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
      renderPost(postWith('the final text'));
      await textCard();
      chooseFiles('the post', photo());
      await mediaOn('the post').findByRole('progressbar');
      const settings = within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', {
        name: 'Settings',
      });

      fireEvent.click(settings);

      expect(confirm).toHaveBeenCalledTimes(1);
      expect(currentPath()).toBe('/posts/post_01');

      confirm.mockReturnValue(true);
      fireEvent.click(settings);

      await waitFor(() => expect(currentPath()).toBe('/settings'));
      confirm.mockRestore();
    });

    it('follows links without asking once no image uploads', async () => {
      const confirm = vi.spyOn(window, 'confirm');
      renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
      await textCard();

      fireEvent.click(
        within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', {
          name: 'Settings',
        }),
      );

      await waitFor(() => expect(currentPath()).toBe('/settings'));
      expect(confirm).not.toHaveBeenCalled();
      confirm.mockRestore();
    });

    it('asks before the New post shortcut leaves while an image uploads', async () => {
      vi.mocked(mediaService.attach).mockReturnValue(new Promise(() => {}));
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
      renderPost(postWith('the final text'));
      await textCard();
      chooseFiles('the post', photo());
      await mediaOn('the post').findByRole('progressbar');
      const shortcut = { key: 'o', shiftKey: true, metaKey: true, ctrlKey: true };

      fireEvent.keyDown(window, shortcut);

      expect(confirm).toHaveBeenCalledTimes(1);
      expect(currentPath()).toBe('/posts/post_01');

      confirm.mockReturnValue(true);
      fireEvent.keyDown(window, shortcut);

      await waitFor(() => expect(currentPath()).toBe('/new'));
      confirm.mockRestore();
    });

    it('takes an image off the server when the page is left during its upload', async () => {
      let answer: (media: Media) => void = () => {};
      vi.mocked(mediaService.attach).mockImplementation(
        () => new Promise((resolve) => (answer = resolve)),
      );
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
      renderPost(postWith('the final text'));
      await textCard();
      chooseFiles('the post', photo());
      await mediaOn('the post').findByRole('progressbar');

      fireEvent.click(
        within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', {
          name: 'Settings',
        }),
      );
      await waitFor(() => expect(currentPath()).toBe('/settings'));
      await act(async () => answer(image('media_09')));

      expect(mediaService.remove).toHaveBeenCalledWith('post_01', 'media_09');
      confirm.mockRestore();
    });

    it('takes an image off the server when its upload is removed, however far it got', async () => {
      let answer: (media: Media) => void = () => {};
      vi.mocked(mediaService.attach).mockImplementation(
        () => new Promise((resolve) => (answer = resolve)),
      );
      renderPost(postWith('the final text'));
      await textCard();
      chooseFiles('the post', photo());
      await mediaOn('the post').findByRole('progressbar');

      fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove image 1' }));
      expect(screen.queryByRole('list', { name: 'Media on the post' })).not.toBeInTheDocument();

      await act(async () => answer(image('media_09')));

      expect(mediaService.remove).toHaveBeenCalledWith('post_01', 'media_09');
      expect(screen.queryByRole('list', { name: 'Media on the post' })).not.toBeInTheDocument();
      expect(track).not.toHaveBeenCalledWith('media_attached', expect.anything());
    });

    it('never sends an image removed while it waits its turn', async () => {
      let answer: (media: Media) => void = () => {};
      vi.mocked(mediaService.attach).mockImplementation(
        () => new Promise((resolve) => (answer = resolve)),
      );
      renderPost(postWith('the final text'));
      await textCard();
      chooseFiles('the post', photo('first.png'), photo('second.png'));
      await mediaOn('the post').findAllByRole('progressbar');

      fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove image 2' }));
      await act(async () => answer(image('media_01')));

      expect(await mediaOn('the post').findByRole('listitem', { name: 'Image 1' })).toBeTruthy();
      expect(mediaService.attach).toHaveBeenCalledTimes(1);
    });

    it('shows an upload whose answer got lost as attached, with no Retry to send it twice', async () => {
      renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
      await textCard();
      vi.mocked(mediaService.attach).mockImplementationOnce(async () => {
        // The server took the file, but its answer never arrived.
        vi.mocked(postService.get).mockResolvedValue(
          withMedia(postWith('the final text'), [[image('media_01'), image('media_taken')]]),
        );
        throw new Error('Network Error');
      });

      chooseFiles('the post', photo('lost.png'));

      const taken = await mediaOn('the post').findByRole('listitem', { name: 'Image 2' });
      await waitFor(() => expect(within(taken).queryByRole('progressbar')).toBeNull());
      expect(mediaOn('the post').getAllByRole('listitem')).toHaveLength(2);
      expect(mediaOn('the post').queryByRole('button', { name: /retry/i })).toBeNull();
      expect(track).toHaveBeenCalledWith('media_attached', {
        kind: 'image',
        via: 'button',
        on: 'text',
        source: 'web',
      });

      fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove image 2' }));
      await waitFor(() =>
        expect(mediaService.remove).toHaveBeenCalledWith('post_01', 'media_taken'),
      );
    });

    it('offers Retry when the server holds no Media from a failed upload', async () => {
      vi.mocked(mediaService.attach).mockRejectedValueOnce(new Error('Network Error'));
      renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
      await textCard();

      chooseFiles('the post', photo('lost.png'));

      expect(
        await mediaOn('the post').findByRole('button', { name: 'Retry lost.png' }),
      ).toBeInTheDocument();
      expect(mediaOn('the post').getAllByRole('listitem', { name: /^Image/ })).toHaveLength(1);
    });

    it('sends the next upload on a Part only once the server Media after a failure are shown', async () => {
      vi.mocked(mediaService.attach)
        .mockRejectedValueOnce(new Error('Network Error'))
        .mockResolvedValueOnce(image('media_02'));
      renderPost(postWith('the final text'));
      await textCard();
      let stored: (post: PostDetail) => void = () => {};
      vi.mocked(postService.get)
        .mockClear()
        .mockImplementation(() => new Promise((resolve) => (stored = resolve)));

      chooseFiles('the post', photo('flaky.png'), photo('next.png'));
      await waitFor(() => expect(postService.get).toHaveBeenCalledTimes(1));
      await act(async () => {});
      expect(mediaService.attach).toHaveBeenCalledTimes(1);

      await act(async () => stored(withMedia(postWith('the final text'), [[]])));

      await waitFor(() => expect(mediaService.attach).toHaveBeenCalledTimes(2));
      const images = await mediaOn('the post').findAllByRole('listitem', { name: /^Image/ });
      await waitFor(() => expect(within(images[0]!).queryByRole('progressbar')).toBeNull());
      expect(mediaOn('the post').getAllByRole('listitem', { name: /^Image/ })).toHaveLength(1);
      expect(mediaOn('the post').getByRole('button', { name: 'Retry flaky.png' })).toBeTruthy();
    });

    it('shows the Media the server holds when it refuses a Part as full', async () => {
      const three = [1, 2, 3].map((n) => image(`media_0${n}`));
      renderPost(withMedia(postWith('the final text'), [three]));
      await textCard();
      vi.mocked(postService.get).mockResolvedValue(
        withMedia(postWith('the final text'), [[...three, image('media_hidden')]]),
      );
      vi.mocked(mediaService.attach).mockRejectedValueOnce(
        apiError(422, 'This post holds 4 images already.', { code: 'MEDIA_PART_FULL' }),
      );

      chooseFiles('the post', photo('late.png'));

      expect(await mediaOn('the post').findByRole('listitem', { name: 'Image 4' })).toBeTruthy();
      expect(
        within(mediaOn('the post').getByRole('listitem', { name: 'late.png' })).getByText(
          'X takes up to 4 images, or 1 GIF, or 1 video, per post',
        ),
      ).toBeInTheDocument();
    });

    it('takes an image dropped on a Part or pasted into its text', async () => {
      vi.mocked(mediaService.attach).mockImplementation(async (_post, part) =>
        image(`media_part_${part}`),
      );
      renderPost(threadOfTwo());
      await textCard();
      const dropped = photo('dropped.png');
      const pasted = photo('pasted.png');

      fireEvent.drop(card().getByRole('listitem', { name: 'Part 2 of 2' }), {
        dataTransfer: { files: [dropped], types: ['Files'] },
      });
      fireEvent.paste(card().getByRole('textbox', { name: 'Part 1 text' }), {
        clipboardData: { files: [pasted], types: ['Files'], getData: () => '' },
      });

      expect(await mediaOn('Part 2').findByRole('listitem', { name: 'Image 1' })).toBeTruthy();
      expect(await mediaOn('Part 1').findByRole('listitem', { name: 'Image 1' })).toBeTruthy();
      expect(mediaService.attach).toHaveBeenCalledWith('post_01', 2, dropped, expect.anything());
      expect(mediaService.attach).toHaveBeenCalledWith('post_01', 1, pasted, expect.anything());
      expect(track).toHaveBeenCalledWith('media_attached', {
        kind: 'image',
        via: 'drop',
        on: 'text',
        source: 'web',
      });
      expect(track).toHaveBeenCalledWith('media_attached', {
        kind: 'image',
        via: 'paste',
        on: 'text',
        source: 'web',
      });
    });

    it('lets a paste of text go into the text box as typed', async () => {
      renderPost(threadOfTwo());
      await textCard();

      fireEvent.paste(card().getByRole('textbox', { name: 'Part 1 text' }), {
        clipboardData: { files: [], types: ['text/plain'], getData: () => 'words' },
      });

      expect(mediaService.attach).not.toHaveBeenCalled();
    });

    it('dims only the words while Feedback writes, never the Media', async () => {
      vi.mocked(postService.addVersion).mockReturnValue(new Promise(() => {}));
      renderPost(withMedia(postWith('the first final'), [[image('media_01')]]));
      await textCard();

      fireEvent.change(panel('Draft').getByRole('textbox', { name: 'Feedback' }), {
        target: { value: 'shorter' },
      });
      const send = panel('Draft').getByRole('button', { name: 'Send feedback' });
      await waitFor(() => expect(send).toBeEnabled());
      fireEvent.click(send);

      await waitFor(() =>
        expect(screen.getByRole('article', { name: 'Text' })).toHaveAttribute('aria-busy', 'true'),
      );
      expect(card().getByText('the first final').closest('.opacity-60')).not.toBeNull();
      expect(
        screen.getByRole('list', { name: 'Media on the post' }).closest('.opacity-60'),
      ).toBeNull();
      expect(card().getByRole('button', { name: 'Add media to the post' })).toBeInTheDocument();
    });

    describe("in X's composer layout", () => {
      function sizedImage(id: string, width: number, height: number): Media {
        return { ...image(id), width, height };
      }

      function frameOf(list: HTMLElement): string {
        return list.style.aspectRatio;
      }

      function cellsOf(list: HTMLElement): string[] {
        return within(list)
          .getAllByRole('listitem')
          .map((tile) => `${tile.style.gridColumn} | ${tile.style.gridRow}`);
      }

      it('shows a single wide image whole, in a frame of its own shape', async () => {
        renderPost(withMedia(postWith('the final text'), [[sizedImage('m1', 1500, 500)]]));
        await textCard();

        expect(frameOf(screen.getByRole('list', { name: 'Media on the post' }))).toBe('3');
      });

      it('keeps a very wide single image tall enough for its Remove button and Alt chip', async () => {
        renderPost(withMedia(postWith('the final text'), [[sizedImage('m1', 3000, 20)]]));
        await textCard();

        const list = screen.getByRole('list', { name: 'Media on the post' });
        expect(frameOf(list)).toBe('150');
        expect(list.style.minHeight).toBe('5rem');
        const tile = within(list).getByRole('listitem', { name: 'Image 1' });
        expect(within(tile).getByRole('button', { name: 'Remove image 1' })).toBeInTheDocument();
        expect(within(tile).getByRole('button', { name: /alt/i })).toBeInTheDocument();
      });

      it.each([
        ['image', 'image'],
        ['GIF', 'gif'],
        ['video', 'video'],
      ] as const)('crops a single tall %s to 3:4', async (_name, kind) => {
        const tall = { ...sizedImage('m1', 1080, 1920), kind };
        renderPost(withMedia(postWith('the final text'), [[tall]]));
        await textCard();

        expect(frameOf(screen.getByRole('list', { name: 'Media on the post' }))).toBe('0.75');
      });

      it.each([
        [2, ['1 | 1', '2 | 1']],
        [3, ['1 | 1 / span 2', '2 | 1', '2 | 2']],
        [4, ['1 | 1', '2 | 1', '1 | 2', '2 | 2']],
      ])("puts %i media in X's cells of a 16:9 frame", async (count, cells) => {
        const media = Array.from({ length: count }, (_, n) => image(`m${n + 1}`));
        renderPost(withMedia(postWith('the final text'), [media]));
        await textCard();

        const list = screen.getByRole('list', { name: 'Media on the post' });
        expect(frameOf(list)).toBe('16 / 9');
        expect(cellsOf(list)).toEqual(cells);
      });

      it('lays more than four media out in two columns, with no frame shape', async () => {
        const five = [1, 2, 3, 4, 5].map((n) => image(`m${n}`));
        renderPost(withMedia(threadOfTwo(), [five, []]));
        await textCard();

        const list = screen.getByRole('list', { name: 'Media on Part 1' });
        expect(frameOf(list)).toBe('');
        expect(cellsOf(list)).toEqual(Array(5).fill(' | '));
        expect(
          screen.getByText(/X takes up to 4 images, or 1 GIF, or 1 video, per post\. Remove/),
        ).toBeInTheDocument();
      });

      it('gives an uploading image its own shape as soon as the browser reads it', async () => {
        vi.mocked(mediaService.attach).mockReturnValue(new Promise(() => {}));
        renderPost(postWith('the final text'));
        await textCard();

        chooseFiles('the post', photo('banner.png'));

        const tile = await mediaOn('the post').findByRole('listitem', { name: 'Image 1' });
        const img = tile.querySelector('img')!;
        Object.defineProperty(img, 'naturalWidth', { value: 1500 });
        Object.defineProperty(img, 'naturalHeight', { value: 500 });
        fireEvent.load(img);

        expect(frameOf(screen.getByRole('list', { name: 'Media on the post' }))).toBe('3');
      });

      it('lays the media out the same way in the "Post to…" confirm step', async () => {
        renderPost(
          withMedia(threadOfTwo(), [
            [sizedImage('m1', 1500, 500)],
            [1, 2, 3].map((n) => image(`m${n + 1}`)),
          ]),
        );
        await textCard();
        fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
        const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));

        fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));

        expect(frameOf(dialog.getByRole('list', { name: 'Media on Part 1' }))).toBe('3');
        const two = dialog.getByRole('list', { name: 'Media on Part 2' });
        expect(frameOf(two)).toBe('16 / 9');
        expect(cellsOf(two)).toEqual(['1 | 1 / span 2', '2 | 1', '2 | 2']);
      });
    });

    describe('GIFs and videos', () => {
      const MINUTE = 60 * 1000;

      function gif(id: string): Media {
        return { ...image(id), kind: 'gif' };
      }

      function video(id: string, durationMs: number | null = 42 * 1000): Media {
        return { ...image(id), kind: 'video', width: 1280, height: 720, durationMs };
      }

      function sized(file: File, size: number): File {
        Object.defineProperty(file, 'size', { value: size });
        return file;
      }

      beforeEach(() => {
        vi.mocked(readVideo)
          .mockReset()
          .mockResolvedValue({ durationMs: 42_000, poster: new Blob(['frame']) });
      });

      afterEach(() => {
        vi.useRealTimers();
      });

      it('shows a GIF with its GIF chip and its Alt chip once it is on', async () => {
        vi.mocked(mediaService.attach).mockResolvedValue(gif('media_01'));
        renderPost(postWith('the final text'));
        await textCard();

        chooseFiles('the post', photo('loop.gif', 'image/gif'));

        const tile = within(await mediaOn('the post').findByRole('listitem', { name: 'GIF 1' }));
        expect(tile.getByText('GIF')).toBeInTheDocument();
        expect(
          await tile.findByRole('button', { name: 'Add alt text to GIF 1' }),
        ).toBeInTheDocument();
        expect(tile.getByRole('button', { name: 'Remove GIF 1' })).toBeInTheDocument();
        expect(readVideo).not.toHaveBeenCalled();
        expect(track).toHaveBeenCalledWith('media_attached', {
          kind: 'gif',
          via: 'button',
          on: 'text',
          source: 'web',
        });
      });

      it('shows a video uploading with its first frame and length, read in the browser and sent with it', async () => {
        let answer: (media: Media) => void = () => {};
        vi.mocked(mediaService.attach).mockReturnValue(
          new Promise((resolve) => (answer = resolve)),
        );
        const poster = new Blob(['frame'], { type: 'image/jpeg' });
        vi.mocked(readVideo).mockResolvedValue({ durationMs: 42_400, poster });
        renderPost(postWith('the final text'));
        await textCard();
        const file = photo('demo.mp4', 'video/mp4');

        chooseFiles('the post', file);

        const shown = await mediaOn('the post').findByRole('listitem', { name: 'Video 1' });
        const tile = within(shown);
        expect(await tile.findByText('0:42')).toBeInTheDocument();
        expect(shown.querySelector('img')).toHaveAttribute('src', 'blob:local-1');
        expect(URL.createObjectURL).toHaveBeenCalledWith(poster);
        expect(tile.getByRole('progressbar', { name: 'Uploading video 1' })).toBeInTheDocument();
        await waitFor(() =>
          expect(mediaService.attach).toHaveBeenCalledWith(
            'post_01',
            1,
            file,
            expect.objectContaining({ video: { durationMs: 42_400, poster } }),
          ),
        );

        await act(async () => answer(video('media_01', 42_400)));

        expect(tile.queryByRole('progressbar')).not.toBeInTheDocument();
        expect(tile.getByText('0:42')).toBeInTheDocument();
        expect(tile.queryByRole('button', { name: /alt text/i })).not.toBeInTheDocument();
      });

      it('shows a video as loading while the browser reads its first frame and length', async () => {
        let read: (facts: { durationMs: number; poster: Blob }) => void = () => {};
        vi.mocked(readVideo).mockReturnValue(new Promise((resolve) => (read = resolve)));
        vi.mocked(mediaService.attach).mockReturnValue(new Promise(() => {}));
        renderPost(postWith('the final text'));
        await textCard();

        chooseFiles('the post', photo('demo.mp4', 'video/mp4'));

        const tile = within(await mediaOn('the post').findByRole('listitem', { name: 'Video 1' }));
        expect(tile.getByRole('status')).toHaveTextContent('Reading video 1');

        await act(async () => read({ durationMs: 42_000, poster: new Blob(['frame']) }));

        expect(tile.queryByRole('status')).not.toBeInTheDocument();
        expect(tile.getByText('0:42')).toBeInTheDocument();
      });

      it('takes a MOV whose type the browser leaves out', async () => {
        vi.mocked(mediaService.attach).mockResolvedValue(video('media_01'));
        renderPost(postWith('the final text'));
        await textCard();

        chooseFiles('the post', photo('IMG_0001.MOV', ''));

        expect(
          await mediaOn('the post').findByRole('listitem', { name: 'Video 1' }),
        ).toBeInTheDocument();
        await waitFor(() => expect(mediaService.attach).toHaveBeenCalled());
      });

      it('shows a video stored without a frame as a muted block with a film icon', async () => {
        renderPost(
          withMedia(postWith('the final text'), [[{ ...video('media_01'), previewUrl: null }]]),
        );
        await textCard();

        const tile = mediaOn('the post').getByRole('listitem', { name: 'Video 1' });
        expect(tile.querySelector('img')).toBeNull();
        expect(tile.querySelector('svg.lucide-film')).not.toBeNull();
        expect(mediaService.preview).not.toHaveBeenCalled();
      });

      it("refuses a GIF over 15 MB and a video over 512 MB on their tiles, naming each one's limit", async () => {
        renderPost(threadOfTwo());
        await textCard();

        chooseFiles('Part 1', sized(photo('loop.gif', 'image/gif'), 15 * MB + 1));
        chooseFiles('Part 2', sized(photo('demo.mov', 'video/quicktime'), 512 * MB + 1));

        expect(
          within(await mediaOn('Part 1').findByRole('listitem', { name: 'loop.gif' })).getByText(
            'Larger than 15 MB',
          ),
        ).toBeInTheDocument();
        expect(
          within(mediaOn('Part 2').getByRole('listitem', { name: 'demo.mov' })).getByText(
            'Larger than 512 MB',
          ),
        ).toBeInTheDocument();
        expect(mediaService.attach).not.toHaveBeenCalled();
      });

      it("refuses mixing kinds on one Part, naming X's rule, and stops taking files once it holds a GIF", async () => {
        renderPost(withMedia(threadOfTwo(), [[image('media_01')], [gif('media_02')]]));
        await textCard();

        chooseFiles('Part 1', photo('demo.mp4', 'video/mp4'));

        const refused = within(
          await mediaOn('Part 1').findByRole('listitem', { name: 'demo.mp4' }),
        );
        expect(
          refused.getByText('X takes up to 4 images, or 1 GIF, or 1 video, per post'),
        ).toBeInTheDocument();
        expect(mediaService.attach).not.toHaveBeenCalled();
        expect(card().getByRole('button', { name: 'Add media to Part 2' })).toHaveAttribute(
          'aria-disabled',
          'true',
        );
        expect(card().getByRole('button', { name: 'Add media to Part 1' })).not.toHaveAttribute(
          'aria-disabled',
        );
      });

      it('warns under a video over 20 minutes when the X account has no Premium', async () => {
        renderPost(withMedia(threadOfTwo(), [[video('media_01', 21 * MINUTE)], []]));
        await textCard();

        expect(
          await screen.findByText(
            'Over 20 minutes: X takes longer videos only from Premium accounts.',
          ),
        ).toBeInTheDocument();
      });

      it('says nothing of a long video on a Premium account, or of a short one', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, premium: true });
        renderPost(
          withMedia(threadOfTwo(), [[video('media_01', 21 * MINUTE)], [video('media_02')]]),
        );
        await textCard();
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

        expect(screen.queryByText(/Over 20 minutes/)).not.toBeInTheDocument();
      });

      it('says nothing of a long video while no X account is connected', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(null);
        renderPost(withMedia(threadOfTwo(), [[video('media_01', 21 * MINUTE)], []]));
        await textCard();
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

        expect(screen.queryByText(/Over 20 minutes/)).not.toBeInTheDocument();
      });

      it('says nothing of a long video a published post went out with', async () => {
        renderPost(
          withScheduledPost({
            ...SCHEDULED,
            state: 'published',
            parts: [{ ...SCHEDULED.parts[0]!, live: true, media: [video('m1', 21 * MINUTE)] }],
          }),
        );
        await textCard();
        await mediaOn('the post').findByRole('listitem', { name: 'Video 1' });
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

        expect(screen.queryByText(/Over 20 minutes/)).not.toBeInTheDocument();
      });

      /** A video upload that has sent `sent` of its bytes, with `bytesLeft` to go, or no news. */
      function sendingUntilAborted(
        progress: { sent: number; bytesLeft: number } | null = {
          sent: 0.1,
          bytesLeft: 400 * MB,
        },
      ): {
        signal: () => AbortSignal | undefined;
        answer: (media: Media) => void;
      } {
        let signal: AbortSignal | undefined;
        let answer: (media: Media) => void = () => {};
        vi.mocked(mediaService.attach).mockImplementation(
          (_post, _part, _file, options) =>
            new Promise((resolve, reject) => {
              signal = options?.signal;
              answer = resolve;
              if (progress) options?.onProgress?.(progress.sent, progress.bytesLeft);
              options?.signal?.addEventListener('abort', () => reject(new CanceledError()));
            }),
        );
        return { signal: () => signal, answer: (media) => answer(media) };
      }

      it.each([
        ['almost all sent', { sent: 0.99, bytesLeft: 4 * MB }],
        ['sent without news of its progress', null],
      ])(
        'lets a video %s finish when its tile is removed, then takes it off the server',
        async (_case, progress) => {
          const sending = sendingUntilAborted(progress);
          renderPost(postWith('the final text'));
          await textCard();
          chooseFiles('the post', photo('demo.mp4', 'video/mp4'));
          await waitFor(() => expect(sending.signal()).toBeDefined());

          fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove video 1' }));
          expect(sending.signal()?.aborted).toBe(false);
          await act(async () => sending.answer(video('media_09')));

          expect(mediaService.remove).toHaveBeenCalledWith('post_01', 'media_09');
          expect(screen.queryByRole('list', { name: 'Media on the post' })).not.toBeInTheDocument();
        },
      );

      it('shows, and keeps, media an app attached while a stopped video was sending', async () => {
        const sending = sendingUntilAborted();
        renderPost(postWith('the final text'));
        await textCard();
        chooseFiles('the post', photo('demo.mp4', 'video/mp4'));
        await waitFor(() => expect(sending.signal()).toBeDefined());
        vi.mocked(postService.get).mockResolvedValue(
          withMedia(postWith('the final text'), [[video('from_an_app')]]),
        );

        fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove video 1' }));

        await waitFor(() =>
          expect(
            mediaOn('the post').getByRole('listitem', { name: 'Video 1' }),
          ).toBeInTheDocument(),
        );
        expect(mediaService.remove).not.toHaveBeenCalled();
      });

      it('stops a video still sending when its tile is removed, attaching nothing', async () => {
        const sending = sendingUntilAborted();
        vi.mocked(postService.get).mockResolvedValue(postWith('the final text'));
        renderPost(postWith('the final text'));
        await textCard();
        chooseFiles('the post', photo('demo.mp4', 'video/mp4'));
        await waitFor(() => expect(sending.signal()).toBeDefined());

        fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove video 1' }));

        expect(sending.signal()?.aborted).toBe(true);
        await waitFor(() => expect(postService.get).toHaveBeenCalled());
        expect(mediaService.remove).not.toHaveBeenCalled();
        expect(screen.queryByRole('list', { name: 'Media on the post' })).not.toBeInTheDocument();
      });

      it('says a video is uploading while "Post to…" waits for it', async () => {
        vi.mocked(mediaService.attach).mockReturnValue(new Promise(() => {}));
        renderPost(postWith('the final text'));
        await textCard();
        chooseFiles('the post', photo('demo.mp4', 'video/mp4'));
        await mediaOn('the post').findByRole('progressbar');

        act(() => card().getByRole('button', { name: 'Post to…' }).focus());

        expect((await screen.findAllByText('A video is still uploading'))[0]).toBeInTheDocument();
      });

      async function postNowWithVideo(answer: ScheduledPost) {
        vi.mocked(scheduledPostService.postNow).mockReset().mockResolvedValue(answer);
        renderPost(withMedia(postWith('the final text'), [[video('media_01')]]));
        await textCard();
        fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
        const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
        fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
        fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));
        return dialog;
      }

      it('shows the post as posting, and says so, when Post now hands it to the publisher', async () => {
        vi.useFakeTimers({ toFake: ['Date'] });
        // The browser's clock runs behind the server's: the answer still says it is posting.
        vi.setSystemTime(new Date('2026-10-10T11:58:00Z'));

        await postNowWithVideo({
          ...SCHEDULED,
          publishAt: '2026-10-10T12:00:00Z',
          parts: [{ ...SCHEDULED.parts[0]!, media: [video('media_01')] }],
          posting: true,
        });

        await dialogClosed();
        expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
        expect(announcedPosting()).toBeInTheDocument();
        expect(screen.queryByText(/X was busy/)).not.toBeInTheDocument();
      });

      it('says X was busy when Post now with a video comes back scheduled but not posting', async () => {
        const dialog = await postNowWithVideo({
          ...SCHEDULED,
          parts: [{ ...SCHEDULED.parts[0]!, media: [video('media_01')] }],
        });

        expect(await dialog.findByText(/X was busy/)).toBeInTheDocument();
      });
    });

    describe('alt text', () => {
      function described(id: string, altText: string): Media {
        return { ...image(id), altText };
      }

      beforeEach(() => {
        vi.mocked(mediaService.setAltText)
          .mockReset()
          .mockImplementation(async (_post, id, altText) => ({ ...image(id), altText }));
      });

      async function openAltText(name: string) {
        fireEvent.click(mediaOn('the post').getByRole('button', { name }));
        return within(await screen.findByRole('dialog', { name: /^Alt text for image/ }));
      }

      it('marks an image without alt text with a hollow Alt chip and one with it with a solid one', async () => {
        renderPost(
          withMedia(postWith('the final text'), [
            [image('media_01'), described('media_02', 'Gulls over the harbour.')],
          ]),
        );
        await textCard();

        const hollow = mediaOn('the post').getByRole('button', { name: 'Add alt text to image 1' });
        const solid = mediaOn('the post').getByRole('button', { name: 'Edit alt text of image 2' });
        expect(hollow).toHaveTextContent('Alt');
        expect(solid).toHaveTextContent('Alt');
        const second = mediaOn('the post').getByRole('listitem', { name: 'Image 2' });
        await waitFor(() =>
          expect(second.querySelector('img')).toHaveAttribute('alt', 'Gulls over the harbour.'),
        );
      });

      it('saves alt text written in the popover and turns the chip solid', async () => {
        renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
        await textCard();

        const popover = await openAltText('Add alt text to image 1');
        const box = popover.getByRole('textbox', { name: 'Alt text' });
        expect(box).toHaveAttribute('maxlength', '1000');
        expect(popover.getByText('0 / 1,000')).toBeInTheDocument();
        fireEvent.change(box, { target: { value: 'Gulls over the harbour.' } });
        expect(popover.getByText('23 / 1,000')).toBeInTheDocument();
        fireEvent.click(popover.getByRole('button', { name: 'Save' }));

        await waitFor(() =>
          expect(screen.queryByRole('dialog', { name: /^Alt text/ })).not.toBeInTheDocument(),
        );
        expect(mediaService.setAltText).toHaveBeenCalledWith(
          'post_01',
          'media_01',
          'Gulls over the harbour.',
        );
        expect(
          mediaOn('the post').getByRole('button', { name: 'Edit alt text of image 1' }),
        ).toHaveFocus();
        expect(track).toHaveBeenCalledWith('media_alt_text_set', {
          kind: 'image',
          cleared: false,
          on: 'text',
          source: 'web',
        });
      });

      it('clears alt text when saved empty', async () => {
        renderPost(withMedia(postWith('the final text'), [[described('media_01', 'Gulls.')]]));
        await textCard();

        const popover = await openAltText('Edit alt text of image 1');
        const box = popover.getByRole('textbox', { name: 'Alt text' });
        expect(box).toHaveValue('Gulls.');
        fireEvent.change(box, { target: { value: '  ' } });
        fireEvent.click(popover.getByRole('button', { name: 'Save' }));

        expect(
          await mediaOn('the post').findByRole('button', { name: 'Add alt text to image 1' }),
        ).toBeInTheDocument();
        expect(mediaService.setAltText).toHaveBeenCalledWith('post_01', 'media_01', null);
        expect(track).toHaveBeenCalledWith('media_alt_text_set', {
          kind: 'image',
          cleared: true,
          on: 'text',
          source: 'web',
        });
      });

      it('saves with Ctrl or ⌘ Enter and closes unsaved with Escape', async () => {
        renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
        await textCard();

        let popover = await openAltText('Add alt text to image 1');
        let box = popover.getByRole('textbox', { name: 'Alt text' });
        expect(box).toHaveFocus();
        fireEvent.change(box, { target: { value: 'Dropped.' } });
        fireEvent.keyDown(box, { key: 'Escape' });
        await waitFor(() =>
          expect(screen.queryByRole('dialog', { name: /^Alt text/ })).not.toBeInTheDocument(),
        );
        expect(mediaService.setAltText).not.toHaveBeenCalled();

        popover = await openAltText('Add alt text to image 1');
        box = popover.getByRole('textbox', { name: 'Alt text' });
        expect(box).toHaveValue('');
        fireEvent.change(box, { target: { value: 'Kept.' } });
        fireEvent.keyDown(box, { key: 'Enter', metaKey: true });

        await waitFor(() =>
          expect(mediaService.setAltText).toHaveBeenCalledWith('post_01', 'media_01', 'Kept.'),
        );
      });

      it('keeps the popover open with what was written when saving fails', async () => {
        vi.mocked(mediaService.setAltText).mockRejectedValue(new Error('Network Error'));
        renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
        await textCard();

        const popover = await openAltText('Add alt text to image 1');
        fireEvent.change(popover.getByRole('textbox', { name: 'Alt text' }), {
          target: { value: 'Gulls.' },
        });
        fireEvent.click(popover.getByRole('button', { name: 'Save' }));

        expect(await popover.findByRole('alert')).toHaveTextContent(
          "Couldn't save the alt text. Try again.",
        );
        expect(popover.getByRole('textbox', { name: 'Alt text' })).toHaveValue('Gulls.');
        expect(
          mediaOn('the post').getByRole('button', { name: 'Add alt text to image 1' }),
        ).toBeInTheDocument();
        expect(track).not.toHaveBeenCalledWith('media_alt_text_set', expect.anything());
      });

      it('holds the popover open and its text fixed while saving, and keeps the draft when the save fails', async () => {
        let fail: (error: Error) => void = () => {};
        vi.mocked(mediaService.setAltText).mockReturnValue(
          new Promise((_resolve, reject) => {
            fail = reject;
          }),
        );
        renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
        await textCard();

        const popover = await openAltText('Add alt text to image 1');
        const box = popover.getByRole('textbox', { name: 'Alt text' });
        fireEvent.change(box, { target: { value: 'Gulls.' } });
        fireEvent.click(popover.getByRole('button', { name: 'Save' }));

        expect(await popover.findByRole('button', { name: 'Saving…' })).toBeDisabled();
        expect(box).toHaveAttribute('readonly');
        fireEvent.keyDown(box, { key: 'Escape' });
        expect(screen.getByRole('dialog', { name: 'Alt text for image 1' })).toBeInTheDocument();

        fail(new Error('Network Error'));
        expect(await popover.findByRole('alert')).toHaveTextContent(
          "Couldn't save the alt text. Try again.",
        );
        expect(box).not.toHaveAttribute('readonly');
        expect(box).toHaveValue('Gulls.');
      });

      it('reopens a popover whose save failed with its draft and the error', async () => {
        vi.mocked(mediaService.setAltText).mockRejectedValue(new Error('Network Error'));
        renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
        await textCard();

        let popover = await openAltText('Add alt text to image 1');
        fireEvent.change(popover.getByRole('textbox', { name: 'Alt text' }), {
          target: { value: 'Gulls.' },
        });
        fireEvent.click(popover.getByRole('button', { name: 'Save' }));
        await popover.findByRole('alert');
        fireEvent.keyDown(popover.getByRole('textbox', { name: 'Alt text' }), { key: 'Escape' });
        await waitFor(() =>
          expect(screen.queryByRole('dialog', { name: /^Alt text/ })).not.toBeInTheDocument(),
        );

        popover = await openAltText('Add alt text to image 1');

        expect(popover.getByRole('textbox', { name: 'Alt text' })).toHaveValue('Gulls.');
        expect(popover.getByRole('alert')).toHaveTextContent(
          "Couldn't save the alt text. Try again.",
        );
      });

      it('puts no Alt chip on an image still uploading', async () => {
        vi.mocked(mediaService.attach).mockReturnValue(new Promise(() => {}));
        renderPost(withMedia(postWith('the final text'), [[]]));
        await textCard();

        chooseFiles('the post', photo());

        await mediaOn('the post').findByRole('listitem', { name: 'Image 1' });
        expect(mediaOn('the post').queryByRole('button', { name: /alt text/i })).toBeNull();
      });
    });

    describe('through rewrites', () => {
      /** Each tile's Media id, read from the preview it shows. */
      async function mediaIdsOn(where: string): Promise<string[]> {
        const tiles = mediaOn(where).getAllByRole('listitem');
        await waitFor(() =>
          tiles.forEach((tile) => expect(tile.querySelector('img')).not.toBeNull()),
        );
        return tiles.map(
          (tile) => tile.querySelector('img')!.getAttribute('src')!.split('/media/')[1]!,
        );
      }

      beforeEach(() => {
        const previews = new WeakMap<Blob, string>();
        vi.mocked(mediaService.preview).mockImplementation(async (url) => {
          const blob = new Blob([url], { type: 'image/webp' });
          previews.set(blob, url);
          return blob;
        });
        URL.createObjectURL = vi.fn((blob: Blob) => `blob:${previews.get(blob) ?? 'local'}`);
      });

      async function sendFeedback(feedback: string) {
        fireEvent.change(panel('Draft').getByRole('textbox', { name: 'Feedback' }), {
          target: { value: feedback },
        });
        const send = panel('Draft').getByRole('button', { name: 'Send feedback' });
        await waitFor(() => expect(send).toBeEnabled());
        fireEvent.click(send);
      }

      const threeParts = () => threadWith([part('one'), part('two'), part('three')]);

      it("keeps each Part's Media where it is through Feedback, and marks only the words", async () => {
        vi.mocked(postService.addVersion).mockResolvedValue(
          version(2, ['uno', 'dos'], { feedback: 'in Spanish' }),
        );
        renderPost(withMedia(threadOfTwo(), [[image('m1')], [image('m2'), image('m3')]]));
        await textCard();

        await sendFeedback('in Spanish');

        expect(await card().findByRole('textbox', { name: 'Part 1 text' })).toHaveValue('uno');
        expect(await mediaIdsOn('Part 1')).toEqual(['m1/preview']);
        expect(await mediaIdsOn('Part 2')).toEqual(['m2/preview', 'm3/preview']);
        await waitFor(() =>
          expect(card().queryAllByText('dos', { selector: '[data-trace]' })).not.toHaveLength(0),
        );
        for (const where of ['Part 1', 'Part 2']) {
          const list = screen.getByRole('list', { name: `Media on ${where}` });
          expect(list.querySelector('[data-trace]')).toBeNull();
          expect(list.closest('.opacity-60')).toBeNull();
        }
      });

      it('moves the Media of Parts Feedback removed last onto the last Part, in order', async () => {
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['short', 'shorter']));
        renderPost(
          withMedia(threeParts(), [[image('m1')], [image('m2')], [image('m3'), image('m4')]]),
        );
        await textCard();

        await sendFeedback('two parts');

        await waitFor(() =>
          expect(card().getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2),
        );
        expect(await mediaIdsOn('Part 1')).toEqual(['m1/preview']);
        expect(await mediaIdsOn('Part 2')).toEqual(['m2/preview', 'm3/preview', 'm4/preview']);
      });

      it("puts every Part's Media on the single post a Thread switches to", async () => {
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['one post']));
        renderPost(withMedia(threadOfTwo(), [[image('m1')], [image('m2')]]));
        await textCard();

        await sendFeedback('condense it');

        expect(await card().findByRole('textbox', { name: 'Post text' })).toHaveValue('one post');
        expect(await mediaIdsOn('the post')).toEqual(['m1/preview', 'm2/preview']);
      });

      it("keeps every tile on a Part over X's rule, says so under them, and Post to refuses it", async () => {
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['one post']));
        renderPost(
          withMedia(threadOfTwo(), [
            [image('m1'), image('m2'), image('m3')],
            [image('m4'), image('m5')],
          ]),
        );
        await textCard();
        expect(card().queryByText(/X takes up to 4 images/)).not.toBeInTheDocument();

        await sendFeedback('condense it');

        expect(
          await card().findByText(
            'X takes up to 4 images, or 1 GIF, or 1 video, per post. Remove some media from the post before posting.',
          ),
        ).toHaveClass('text-destructive');
        expect(mediaOn('the post').getAllByRole('listitem')).toHaveLength(5);
        expect(card().getByRole('button', { name: 'Add media to the post' })).toHaveAttribute(
          'aria-disabled',
          'true',
        );
        fireEvent.click(card().getByRole('button', { name: 'Post to…' }));
        const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
        expect(
          dialog.getByText(
            'This post has more media than X takes. X takes up to 4 images, or 1 GIF, or 1 video, per post.',
          ),
        ).toBeInTheDocument();
      });

      it('moves the Media of Parts a restored Version lacks onto its last Part', async () => {
        const versions = [version(1, ['the first']), version(2, ['two a', 'two b'])];
        vi.mocked(postService.restoreVersion).mockResolvedValue(textOf(versions[0]!));
        renderPost(withMedia(draft(versions), [[image('m1')], [image('m2')]]));
        await textCard();

        fireEvent.click(card().getByRole('button', { name: 'History' }));
        const history = within(await screen.findByRole('dialog', { name: 'History' }));
        fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));

        expect(await card().findByRole('textbox', { name: 'Post text' })).toHaveValue('the first');
        expect(await mediaIdsOn('the post')).toEqual(['m1/preview', 'm2/preview']);
      });

      it('keeps the tiles at full strength while Pumpkit writes, dimming only the words', async () => {
        vi.mocked(postService.addVersion).mockReturnValue(new Promise(() => {}));
        renderPost(withMedia(threadOfTwo(), [[image('m1')], [image('m2')]]));
        await textCard();

        await sendFeedback('in Spanish');

        await waitFor(() =>
          expect(screen.getByRole('article', { name: 'Text' })).toHaveAttribute(
            'aria-busy',
            'true',
          ),
        );
        expect(card().getAllByText('one')[0]!.closest('.opacity-60')).not.toBeNull();
        for (const where of ['Part 1', 'Part 2']) {
          const list = screen.getByRole('list', { name: `Media on ${where}` });
          expect(list.closest('.opacity-60')).toBeNull();
        }
      });

      it('leaves tiles on their Part when an undo that would drop it fails', async () => {
        const versions = [version(1, ['a', 'b', 'c']), version(2, ['x', 'y'])];
        vi.mocked(postService.restoreVersion)
          .mockResolvedValueOnce(textOf(versions[0]!))
          .mockRejectedValueOnce(apiError(409, 'Version 2 is gone.'));
        vi.mocked(mediaService.attach).mockResolvedValue(image('m3'));
        renderPost(withMedia(draft(versions), [[], [image('m2')]]));
        await textCard();
        fireEvent.click(card().getByRole('button', { name: 'History' }));
        const history = within(await screen.findByRole('dialog', { name: 'History' }));
        fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));
        expect(await card().findByRole('textbox', { name: 'Part 3 text' })).toHaveValue('c');
        chooseFiles('Part 3', new File([new Uint8Array(8)], 'three.png', { type: 'image/png' }));
        await waitFor(() => expect(mediaIdsOn('Part 3')).resolves.toEqual(['m3/preview']));

        fireEvent.click(card().getByRole('button', { name: 'Undo' }));

        expect(await screen.findByText('Version 2 is gone.')).toBeInTheDocument();
        expect(card().getByRole('textbox', { name: 'Part 3 text' })).toHaveValue('c');
        expect(await mediaIdsOn('Part 2')).toEqual(['m2/preview']);
        expect(await mediaIdsOn('Part 3')).toEqual(['m3/preview']);
      });

      it('takes off an image whose removal ends after Feedback moved it to another Part', async () => {
        let removed: () => void = () => {};
        vi.mocked(mediaService.remove).mockReturnValue(new Promise((done) => (removed = done)));
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['short', 'shorter']));
        renderPost(withMedia(threeParts(), [[image('m1')], [image('m2')], [image('m3')]]));
        await textCard();

        fireEvent.click(mediaOn('Part 3').getByRole('button', { name: 'Remove image 1' }));
        await sendFeedback('two parts');
        await waitFor(() =>
          expect(card().getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2),
        );
        await act(async () => removed());

        expect(await mediaIdsOn('Part 2')).toEqual(['m2/preview']);
        fireEvent.click(card().getByRole('button', { name: 'Post to…' }));
        expect(await screen.findByRole('dialog', { name: 'Post to…' })).toBeInTheDocument();
      });

      it('shows an upload that landed before Feedback dropped its Part where the server moved it', async () => {
        let lost: (error: Error) => void = () => {};
        vi.mocked(mediaService.attach).mockReturnValue(new Promise((_, fail) => (lost = fail)));
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['short', 'shorter']));
        renderPost(withMedia(threeParts(), [[], [], []]));
        await textCard();

        chooseFiles('Part 3', new File([new Uint8Array(8)], 'late.png', { type: 'image/png' }));
        await sendFeedback('two parts');
        await waitFor(() =>
          expect(card().getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2),
        );
        vi.mocked(postService.get).mockResolvedValue(
          withMedia(threadWith([part('short'), part('shorter')]), [[], [image('landed')]]),
        );
        await act(async () => lost(new Error('Network Error')));

        await waitFor(() => expect(mediaIdsOn('Part 2')).resolves.toEqual(['landed/preview']));
        expect(card().queryByRole('button', { name: 'Retry late.png' })).not.toBeInTheDocument();
      });

      it('sends one upload at a time across the Text, onto a Part Feedback merged too', async () => {
        let answer: (media: Media) => void = () => {};
        vi.mocked(mediaService.attach)
          .mockImplementationOnce(() => new Promise((resolve) => (answer = resolve)))
          .mockResolvedValueOnce(image('second'));
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['short', 'shorter']));
        renderPost(withMedia(threeParts(), [[], [], []]));
        await textCard();

        chooseFiles('Part 3', photo('first.png'));
        await sendFeedback('two parts');
        await waitFor(() =>
          expect(card().getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2),
        );
        chooseFiles('Part 2', photo('second.png'));
        await act(async () => {});
        expect(mediaService.attach).toHaveBeenCalledTimes(1);
        vi.mocked(postService.get).mockResolvedValue(
          withMedia(threadWith([part('short'), part('shorter')]), [[], [image('first')]]),
        );

        await act(async () => answer(image('first')));

        await waitFor(() => expect(mediaService.attach).toHaveBeenCalledTimes(2));
        await waitFor(() =>
          expect(mediaIdsOn('Part 2')).resolves.toEqual(['first/preview', 'second/preview']),
        );
      });

      it('shows an upload Feedback moved in the order the server put it, after Media already there', async () => {
        let answer: (media: Media) => void = () => {};
        vi.mocked(mediaService.attach).mockReturnValueOnce(
          new Promise((resolve) => (answer = resolve)),
        );
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['short', 'shorter']));
        renderPost(withMedia(threeParts(), [[], [], [image('m3')]]));
        await textCard();

        chooseFiles('Part 2', photo('new.png'));
        await sendFeedback('two parts');
        await waitFor(() =>
          expect(card().getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2),
        );
        vi.mocked(postService.get).mockResolvedValue(
          withMedia(threadWith([part('short'), part('shorter')]), [
            [],
            [image('m3'), image('new')],
          ]),
        );
        await act(async () => answer(image('new')));

        await waitFor(() =>
          expect(mediaIdsOn('Part 2')).resolves.toEqual(['m3/preview', 'new/preview']),
        );
      });

      it('sends an upload again to the Part its tile moved to when its Part went away on the server', async () => {
        vi.mocked(mediaService.attach)
          .mockRejectedValueOnce(apiError(404, "This post's text has no part 3."))
          .mockResolvedValueOnce(image('moved'));
        renderPost(withMedia(threeParts(), [[], [], []]));
        await textCard();
        // Feedback from another tab left the Text with two Parts.
        vi.mocked(postService.get).mockResolvedValue(
          withMedia(threadWith([part('short'), part('shorter')]), [[], []]),
        );

        chooseFiles('Part 3', photo('late.png'));

        await waitFor(() => expect(mediaIdsOn('Part 2')).resolves.toEqual(['moved/preview']));
        expect(vi.mocked(mediaService.attach).mock.calls.map((call) => call[1])).toEqual([3, 2]);
        expect(card().queryByText(/no part 3/)).not.toBeInTheDocument();
      });

      it('keeps the Media the server moved when a failed upload reads back a Part that went away', async () => {
        vi.mocked(mediaService.attach).mockRejectedValueOnce(new Error('Network Error'));
        renderPost(withMedia(threeParts(), [[], [], [image('m3')]]));
        await textCard();
        vi.mocked(postService.get).mockResolvedValue(
          withMedia(threadWith([part('short'), part('shorter')]), [[], [image('m3')]]),
        );

        chooseFiles('Part 3', photo('late.png'));

        await waitFor(() =>
          expect(mediaOn('Part 2').getByRole('button', { name: 'Retry late.png' })).toBeTruthy(),
        );
        const kept = mediaOn('Part 2').getByRole('listitem', { name: 'Image 1' });
        await waitFor(() =>
          expect(kept.querySelector('img')).toHaveAttribute('src', 'blob:/media/m3/preview'),
        );
      });

      it('takes no files on a Part an undo shows until the undo lands', async () => {
        const versions = [version(1, ['a', 'b', 'c']), version(2, ['x', 'y'])];
        let undone: (text: PostText) => void = () => {};
        vi.mocked(postService.restoreVersion)
          .mockResolvedValueOnce(textOf(versions[0]!))
          .mockResolvedValueOnce(textOf(versions[1]!))
          .mockReturnValueOnce(new Promise((resolve) => (undone = resolve)));
        renderPost(withMedia(draft(versions), [[], [image('m2')]]));
        await textCard();
        for (const number of [1, 2]) {
          fireEvent.click(card().getByRole('button', { name: 'History' }));
          const history = within(await screen.findByRole('dialog', { name: 'History' }));
          fireEvent.click(history.getByRole('button', { name: new RegExp(`^Version ${number}`) }));
          await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        }
        await waitFor(() =>
          expect(card().getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2),
        );

        fireEvent.click(card().getByRole('button', { name: 'Undo' }));
        expect(await card().findByRole('textbox', { name: 'Part 3 text' })).toHaveValue('c');
        const button = card().getByRole('button', { name: 'Add media to Part 3' });
        expect(button).toHaveAttribute('aria-disabled', 'true');
        fireEvent.pointerMove(button, { pointerType: 'mouse' });
        expect(await screen.findByRole('tooltip')).toHaveTextContent(
          "Saving this part. Add media once it's saved.",
        );
        chooseFiles('Part 3', photo('three.png'));
        fireEvent.drop(card().getByRole('listitem', { name: 'Part 3 of 3' }), {
          dataTransfer: { files: [photo('dropped.png')], types: ['Files'] },
        });
        await act(async () => {});

        expect(mediaService.attach).not.toHaveBeenCalled();
        expect(
          screen.getAllByText("Saving this part. Add media once it's saved.").length,
        ).toBeGreaterThan(1);
        expect(screen.queryByRole('list', { name: 'Media on Part 3' })).not.toBeInTheDocument();
        expect(await mediaIdsOn('Part 2')).toEqual(['m2/preview']);

        await act(async () => undone(textOf(versions[0]!)));

        await waitFor(() =>
          expect(card().getByRole('button', { name: 'Add media to Part 3' })).not.toHaveAttribute(
            'aria-disabled',
          ),
        );
      });

      it('keeps tiles on the Parts shown when a read from before Feedback answers after it', async () => {
        vi.mocked(mediaService.attach).mockRejectedValueOnce(new Error('Network Error'));
        vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['short', 'shorter']));
        const before = withMedia(threeParts(), [[], [], [image('m3')]]);
        renderPost(before);
        await textCard();
        let readBack: (post: PostDetail) => void = () => {};
        vi.mocked(postService.get).mockReturnValueOnce(
          new Promise((resolve) => (readBack = resolve)),
        );

        chooseFiles('Part 1', photo('late.png'));
        await waitFor(() => expect(postService.get).toHaveBeenCalledTimes(2));
        await sendFeedback('two parts');
        await waitFor(() =>
          expect(card().getAllByRole('listitem', { name: /^Part \d of 2$/ })).toHaveLength(2),
        );
        await act(async () => readBack(before));

        await waitFor(() =>
          expect(mediaOn('Part 1').getByRole('button', { name: 'Retry late.png' })).toBeTruthy(),
        );
        expect(await mediaIdsOn('Part 2')).toEqual(['m3/preview']);
      });

      it('leaves Media be when a text edit is undone and redone', async () => {
        vi.mocked(postService.saveText).mockImplementation(async (_postId, texts) => ({
          format: 'thread',
          parts: texts.map((text) => part(text)),
          versionNumber: 1,
          edited: true,
        }));
        renderPost(withMedia(threadOfTwo(), [[image('m1')], [image('m2')]]));
        const box = (await textCard()).getByRole('textbox', { name: 'Part 2 text' });

        fireEvent.change(box, { target: { value: 'two, edited' } });
        fireEvent.click(card().getByRole('button', { name: 'Undo' }));
        expect(box).toHaveValue('two');
        fireEvent.click(card().getByRole('button', { name: 'Redo' }));
        expect(box).toHaveValue('two, edited');

        expect(await mediaIdsOn('Part 1')).toEqual(['m1/preview']);
        expect(await mediaIdsOn('Part 2')).toEqual(['m2/preview']);
      });
    });

    describe('once it goes to X', () => {
      async function openPostTo(post: PostDetail): Promise<Dialog> {
        renderPost(post);
        await textCard();
        fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
        return within(await screen.findByRole('dialog', { name: 'Post to…' }));
      }

      function scheduledWith(state: ScheduledPost['state'], media: Media[]): PostDetail {
        return withScheduledPost({
          ...SCHEDULED,
          state,
          parts: [{ ...SCHEDULED.parts[0]!, live: state === 'published', media }],
        });
      }

      it("shows each Part's media read-only under its text in the confirm step", async () => {
        const dialog = await openPostTo(withMedia(threadOfTwo(), [[], [image('m1'), image('m2')]]));

        fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));

        const two = within(dialog.getByRole('listitem', { name: 'Part 2' }));
        const tiles = within(two.getByRole('list', { name: 'Media on Part 2' }));
        expect(
          tiles.getAllByRole('listitem').map((tile) => tile.getAttribute('aria-label')),
        ).toEqual(['Image 1', 'Image 2']);
        expect(tiles.queryByRole('button')).not.toBeInTheDocument();
        expect(dialog.queryByRole('list', { name: 'Media on Part 1' })).not.toBeInTheDocument();
      });

      it('waits to open while an image uploads, saying why, then opens once it is on', async () => {
        let answer: (media: Media) => void = () => {};
        vi.mocked(mediaService.attach).mockReturnValue(
          new Promise((resolve) => (answer = resolve)),
        );
        renderPost(threadOfTwo());
        await textCard();
        chooseFiles('Part 2', photo());
        await mediaOn('Part 2').findByRole('progressbar');

        const postTo = card().getByRole('button', { name: 'Post to…' });
        expect(postTo).toHaveAttribute('aria-disabled', 'true');
        act(() => postTo.focus());
        expect((await screen.findAllByText('An image is still uploading'))[0]).toBeInTheDocument();
        fireEvent.click(postTo);
        expect(screen.queryByRole('dialog', { name: 'Post to…' })).not.toBeInTheDocument();

        await act(async () => answer(image('media_01')));

        expect(postTo).not.toHaveAttribute('aria-disabled');
        fireEvent.click(postTo);
        const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
        fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
        expect(dialog.getByRole('list', { name: 'Media on Part 2' })).toBeInTheDocument();
      });

      it('waits to open while an image is being removed, saying why', async () => {
        vi.mocked(mediaService.remove).mockReturnValue(new Promise(() => {}));
        renderPost(withMedia(postWith('the final text'), [[image('media_01')]]));
        await textCard();

        fireEvent.click(mediaOn('the post').getByRole('button', { name: 'Remove image 1' }));

        const postTo = card().getByRole('button', { name: 'Post to…' });
        expect(postTo).toHaveAttribute('aria-disabled', 'true');
        act(() => postTo.focus());
        expect(
          (await screen.findAllByText('An image is still being removed'))[0],
        ).toBeInTheDocument();
        fireEvent.click(postTo);
        expect(screen.queryByRole('dialog', { name: 'Post to…' })).not.toBeInTheDocument();
      });

      it("won't post a Part holding more media than X takes, and names the Part", async () => {
        const five = ['a', 'b', 'c', 'd', 'e'].map(image);
        const dialog = await openPostTo(withMedia(threadOfTwo(), [five, []]));

        expect(
          dialog.getByText(
            'Part 1 has more media than X takes. X takes up to 4 images, or 1 GIF, or 1 video, per post.',
          ),
        ).toBeInTheDocument();
        expect(dialog.getByRole('button', { name: 'Review and post' })).toBeDisabled();
      });

      it("shows a scheduled post's media read-only on the card", async () => {
        renderPost(scheduledWith('scheduled', [image('m1')]));
        await textCard();

        const tiles = mediaOn('the post');
        expect(await tiles.findByRole('listitem', { name: 'Image 1' })).toBeInTheDocument();
        expect(tiles.queryByRole('button')).not.toBeInTheDocument();
        expect(card().queryByRole('button', { name: /add media/i })).not.toBeInTheDocument();
        await waitFor(() =>
          expect(mediaService.preview).toHaveBeenCalledWith('/media/m1/preview', expect.anything()),
        );
      });

      it('keeps showing the preview of the media a published post went out with', async () => {
        renderPost(scheduledWith('published', [image('m1')]));
        await textCard();

        const tile = await mediaOn('the post').findByRole('listitem', { name: 'Image 1' });
        await waitFor(() =>
          expect(tile.querySelector('img')).toHaveAttribute('src', 'blob:local-1'),
        );
        expect(within(tile).queryByRole('button')).not.toBeInTheDocument();
      });

      it("shows a failed thread's live Part media read-only and lets the rest change", async () => {
        renderPost({
          ...withMedia(threadOfTwo(), [[image('t1')], []]),
          status: 'failed',
          scheduledPost: {
            ...SCHEDULED,
            state: 'failed',
            failedReason: 'X refused part 2: Nope',
            parts: [
              {
                text: 'one',
                live: true,
                xPostUrl: 'https://x.com/i/web/status/1',
                media: [image('live1')],
              },
              { text: 'two', live: false, xPostUrl: null, media: [] },
            ],
          },
        });
        await textCard();

        const one = mediaOn('Part 1');
        expect(await one.findByRole('listitem', { name: 'Image 1' })).toBeInTheDocument();
        expect(one.queryByRole('button')).not.toBeInTheDocument();
        await waitFor(() =>
          expect(mediaService.preview).toHaveBeenCalledWith(
            '/media/live1/preview',
            expect.anything(),
          ),
        );
        expect(
          card().queryByRole('button', { name: 'Add media to Part 1' }),
        ).not.toBeInTheDocument();
        expect(card().getByRole('button', { name: 'Add media to Part 2' })).toBeInTheDocument();
      });
    });

    describe('on an X connection made before X allowed media', () => {
      const BEFORE_MEDIA: XConnection = { ...CONNECTED, needsReconnectForMedia: true };

      let picker: MockInstance<HTMLInputElement['click']>;

      beforeEach(() => {
        picker = vi.spyOn(HTMLInputElement.prototype, 'click');
      });

      afterEach(() => {
        picker.mockRestore();
      });

      it('opens the reconnect X dialog instead of the file picker', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(BEFORE_MEDIA);
        vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
          'https://x.com/i/oauth2/authorize?state=s',
        );
        renderPost(postWith('the final text'));
        await textCard();
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

        fireEvent.click(card().getByRole('button', { name: 'Add media to the post' }));

        const dialog = within(
          await screen.findByRole('dialog', { name: 'Reconnect X to add media' }),
        );
        expect(picker).not.toHaveBeenCalled();
        expect(dialog.getByText(/@ada/)).toBeInTheDocument();
        fireEvent.click(dialog.getByRole('button', { name: 'Reconnect X' }));
        await waitFor(() =>
          expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
        );
        expect(xConnectionReturn.take()).toBe('/posts/post_01');
      });

      it('closes the dialog with Not now, sending nothing', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(BEFORE_MEDIA);
        vi.mocked(xConnectionService.startAuthorization).mockClear();
        renderPost(postWith('the final text'));
        await textCard();
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

        fireEvent.click(card().getByRole('button', { name: 'Add media to the post' }));
        fireEvent.click(await screen.findByRole('button', { name: 'Not now' }));

        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(xConnectionService.startAuthorization).not.toHaveBeenCalled();
      });

      it('opens the dialog for an image dropped on a Part, sending nothing', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(BEFORE_MEDIA);
        renderPost(postWith('the final text'));
        await textCard();
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

        fireEvent.drop(card().getByRole('listitem', { name: 'Post' }), {
          dataTransfer: { files: [photo()], types: ['Files'] },
        });

        expect(
          await screen.findByRole('dialog', { name: 'Reconnect X to add media' }),
        ).toBeInTheDocument();
        expect(mediaService.attach).not.toHaveBeenCalled();
      });

      it('opens the dialog when the server asks to reconnect, leaving no tile', async () => {
        vi.mocked(mediaService.attach).mockRejectedValue(
          apiError(409, 'Reconnect X so Pumpkit can post media on your X account.', {
            code: 'X_RECONNECT_FOR_MEDIA',
          }),
        );
        renderPost(postWith('the final text'));
        await textCard();

        chooseFiles('the post', photo());

        expect(
          await screen.findByRole('dialog', { name: 'Reconnect X to add media' }),
        ).toBeInTheDocument();
        expect(screen.queryByRole('list', { name: 'Media on the post' })).not.toBeInTheDocument();
      });

      it('asks to reconnect on later clicks once the server has refused an upload', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
        vi.mocked(mediaService.attach).mockRejectedValue(
          apiError(409, 'Reconnect X so Pumpkit can post media on your X account.', {
            code: 'X_RECONNECT_FOR_MEDIA',
          }),
        );
        renderPost(postWith('the final text'));
        await textCard();
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());
        vi.mocked(xConnectionService.get).mockResolvedValue(BEFORE_MEDIA);
        chooseFiles('the post', photo());
        fireEvent.click(await screen.findByRole('button', { name: 'Not now' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalledTimes(2));
        await act(async () => {});
        picker.mockClear();

        fireEvent.click(card().getByRole('button', { name: 'Add media to the post' }));

        expect(
          await screen.findByRole('dialog', { name: 'Reconnect X to add media' }),
        ).toBeInTheDocument();
        expect(picker).not.toHaveBeenCalled();
        expect(mediaService.attach).toHaveBeenCalledTimes(1);
      });
    });

    it("shows the X callback's message on arriving back from reconnecting", async () => {
      vi.mocked(postService.get).mockResolvedValue(postWith('the final text'));
      renderSignedIn('/posts/post_01', { state: { xConnectionNotice: 'Connected @ada.' } });

      expect(await screen.findByText('Connected @ada.')).toBeInTheDocument();
    });

    it('attaches media without an X connection', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(null);
      vi.mocked(mediaService.attach).mockResolvedValue(image('media_01'));
      renderPost(postWith('the final text'));
      await textCard();
      await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

      chooseFiles('the post', photo());

      expect(await mediaOn('the post').findByRole('listitem', { name: 'Image 1' })).toBeTruthy();
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('shows no media controls once the Post is scheduled', async () => {
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();

      expect(screen.queryByRole('button', { name: /add media/i })).not.toBeInTheDocument();
    });

    describe("on a scheduled post's edit", () => {
      const THREAD: ScheduledPost = {
        ...SCHEDULED,
        parts: [
          { text: 'Live one.', live: true, xPostUrl: 'https://x.com/i/web/status/1', media: [] },
          { text: 'Two.', live: false, xPostUrl: null, media: [] },
        ],
      };

      beforeEach(() => {
        // Before SCHEDULED's time: a posting Scheduled post offers no Edit.
        vi.useFakeTimers({ toFake: ['Date'] });
        vi.setSystemTime(new Date('2026-10-10T12:00:00Z'));
        vi.mocked(mediaService.attachToScheduledPost).mockReset();
        vi.mocked(mediaService.removeFromScheduledPost).mockReset().mockResolvedValue();
        vi.mocked(scheduledPostService.edit).mockReset();
      });

      afterEach(() => {
        vi.useRealTimers();
      });

      async function startEditing(scheduledPost: ScheduledPost) {
        renderPost(withScheduledPost(scheduledPost));
        await textCard();
        fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
        return within(await screen.findByRole('region', { name: 'Edit the scheduled post' }));
      }

      it("attaches an image to the scheduled post's own copy, not to the Text", async () => {
        vi.mocked(mediaService.attachToScheduledPost).mockResolvedValue(image('media_02'));
        await startEditing(THREAD);
        const file = photo();

        chooseFiles('Part 2', file);

        expect(await mediaOn('Part 2').findByRole('listitem', { name: 'Image 1' })).toBeTruthy();
        expect(mediaService.attachToScheduledPost).toHaveBeenCalledWith(
          'scheduled_post_01',
          2,
          file,
          expect.anything(),
        );
        expect(mediaService.attach).not.toHaveBeenCalled();
        expect(track).toHaveBeenCalledWith('media_attached', {
          kind: 'image',
          via: 'button',
          on: 'scheduled_post',
          source: 'web',
        });
      });

      it("writes alt text on the scheduled post's own copy", async () => {
        vi.mocked(mediaService.setScheduledPostAltText).mockImplementation(
          async (_sp, id, altText) => ({ ...image(id), altText }),
        );
        await startEditing({
          ...THREAD,
          parts: [THREAD.parts[0]!, { ...THREAD.parts[1]!, media: [image('m1')] }],
        });

        fireEvent.click(mediaOn('Part 2').getByRole('button', { name: 'Add alt text to image 1' }));
        const popover = within(await screen.findByRole('dialog', { name: 'Alt text for image 1' }));
        fireEvent.change(popover.getByRole('textbox', { name: 'Alt text' }), {
          target: { value: 'A bar chart.' },
        });
        fireEvent.click(popover.getByRole('button', { name: 'Save' }));

        expect(
          await mediaOn('Part 2').findByRole('button', { name: 'Edit alt text of image 1' }),
        ).toBeInTheDocument();
        expect(mediaService.setScheduledPostAltText).toHaveBeenCalledWith(
          'scheduled_post_01',
          'm1',
          'A bar chart.',
        );
        expect(mediaService.setAltText).not.toHaveBeenCalled();
      });

      it("shows a live Part's alt text without a chip to change it", async () => {
        await startEditing({
          ...THREAD,
          parts: [
            { ...THREAD.parts[0]!, media: [{ ...image('media_01'), altText: 'Sent.' }] },
            THREAD.parts[1]!,
          ],
        });

        const one = (await textCard()).getByRole('listitem', { name: 'Part 1 of 2' });
        expect(within(one).queryByRole('button', { name: /alt text/i })).toBeNull();
        await waitFor(() =>
          expect(
            within(one).getByRole('listitem', { name: 'Image 1' }).querySelector('img'),
          ).toHaveAttribute('alt', 'Sent.'),
        );
      });

      it("shows a live Part's media read-only, with no media button", async () => {
        await startEditing({
          ...THREAD,
          parts: [{ ...THREAD.parts[0]!, media: [image('media_01')] }, THREAD.parts[1]!],
        });

        const one = (await textCard()).getByRole('listitem', { name: 'Part 1 of 2' });
        expect(within(one).getByRole('listitem', { name: 'Image 1' })).toBeInTheDocument();
        expect(within(one).queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
        expect(within(one).queryByRole('button', { name: /add media/i })).not.toBeInTheDocument();
        expect(card().getByRole('button', { name: 'Add media to Part 2' })).toBeInTheDocument();
      });

      it("removes an image from the scheduled post's copy, which the card shows after Cancel", async () => {
        const editor = await startEditing({
          ...THREAD,
          parts: [THREAD.parts[0]!, { ...THREAD.parts[1]!, media: [image('m1'), image('m2')] }],
        });

        fireEvent.click(mediaOn('Part 2').getByRole('button', { name: 'Remove image 1' }));
        await waitFor(() => expect(mediaOn('Part 2').getAllByRole('listitem')).toHaveLength(1));
        fireEvent.click(editor.getByRole('button', { name: 'Cancel' }));

        expect(mediaService.removeFromScheduledPost).toHaveBeenCalledWith(
          'scheduled_post_01',
          'm1',
        );
        expect(mediaService.remove).not.toHaveBeenCalled();
        await panel('Scheduled').findByRole('button', { name: 'Edit' });
        const tiles = mediaOn('Part 2').getAllByRole('listitem');
        expect(tiles).toHaveLength(1);
        expect(mediaOn('Part 2').queryByRole('button')).not.toBeInTheDocument();
      });

      it('waits to save while an image uploads, saying why', async () => {
        let answer: (media: Media) => void = () => {};
        vi.mocked(mediaService.attachToScheduledPost).mockReturnValue(
          new Promise((resolve) => (answer = resolve)),
        );
        vi.mocked(scheduledPostService.edit).mockResolvedValue(THREAD);
        const editor = await startEditing(THREAD);
        fireEvent.change(card().getByRole('textbox', { name: 'Part 2 text' }), {
          target: { value: 'Two, edited.' },
        });
        chooseFiles('Part 2', photo());

        await mediaOn('Part 2').findByRole('progressbar');
        const save = editor.getByRole('button', { name: 'Save changes' });
        expect(save).toHaveAttribute('aria-disabled', 'true');
        act(() => save.focus());
        expect((await screen.findAllByText('An image is still uploading'))[0]).toBeInTheDocument();
        fireEvent.click(save);
        expect(scheduledPostService.edit).not.toHaveBeenCalled();

        await act(async () => answer(image('media_02')));
        expect(save).not.toHaveAttribute('aria-disabled');
        fireEvent.click(save);

        await waitFor(() =>
          expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
            parts: ['Live one.', 'Two, edited.'],
          }),
        );
      });

      it('asks to reconnect X instead of taking files on a connection made before media', async () => {
        vi.mocked(xConnectionService.get).mockResolvedValue({
          ...CONNECTED,
          needsReconnectForMedia: true,
        });
        await startEditing(THREAD);
        await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());

        fireEvent.click(card().getByRole('button', { name: 'Add media to Part 2' }));

        expect(
          await screen.findByRole('dialog', { name: 'Reconnect X to add media' }),
        ).toBeInTheDocument();
        expect(mediaService.attachToScheduledPost).not.toHaveBeenCalled();
      });
    });
  });

  describe('Undo and redo', () => {
    const TWO = [
      version(1, ['the first text']),
      version(2, ['the second text'], { feedback: 'Punchier hook' }),
    ];

    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      vi.mocked(postService.saveText)
        .mockReset()
        .mockImplementation(async (_postId, texts) => ({
          format: 'post',
          parts: texts.map((text) => part(text)),
          versionNumber: 1,
          edited: true,
        }));
      vi.mocked(postService.restoreVersion).mockImplementation(async (_postId, n) =>
        textOf(TWO[n - 1]!),
      );
      Element.prototype.scrollIntoView = vi.fn();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    async function pause(ms: number) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
    }

    const button = (name: string) => card().getByRole('button', { name });
    const origin = (name: string) => card().findByRole('button', { name });

    async function postBox() {
      return (await textCard()).getByRole('textbox', { name: 'Post text' });
    }

    /** Waits for the box to hold `text`; a rewrite's marks repeat its words under the box. */
    async function boxHolds(text: string) {
      await waitFor(() =>
        expect(screen.getByRole('textbox', { name: 'Post text' })).toHaveValue(text),
      );
    }

    async function sendFeedback(feedback: string) {
      await textCard();
      fireEvent.change(panel('Draft').getByRole('textbox', { name: 'Feedback' }), {
        target: { value: feedback },
      });
      fireEvent.click(panel('Draft').getByRole('button', { name: 'Send feedback' }));
    }

    it('starts with nothing to undo or redo, as after a reload', async () => {
      renderPost(postWith('the final text'));
      await textCard();

      expect(button('Undo')).toBeDisabled();
      expect(button('Redo')).toBeDisabled();
    });

    it('undoes and redoes each burst of typing, saving the Text it lands on', async () => {
      renderPost(postWith('the final text'));
      const box = await postBox();

      fireEvent.change(box, { target: { value: 'the final text,' } });
      fireEvent.change(box, { target: { value: 'the final text, again' } });
      await pause(1_000);
      fireEvent.change(box, { target: { value: 'the final text, again!' } });

      fireEvent.click(button('Undo'));
      expect(box).toHaveValue('the final text, again');
      fireEvent.click(button('Undo'));
      expect(box).toHaveValue('the final text');
      expect(button('Undo')).toBeDisabled();
      expect(await origin('V1 · From your brief')).toBeInTheDocument();
      expect(await screen.findByText('Undid: your edit')).toBeInTheDocument();
      await pause(TEXT_SAVE_PAUSE_MS);
      expect(postService.saveText).toHaveBeenLastCalledWith('post_01', ['the final text']);

      fireEvent.click(button('Redo'));
      expect(box).toHaveValue('the final text, again');
      expect(await origin('V1 · From your brief · edited')).toBeInTheDocument();
      await pause(TEXT_SAVE_PAUSE_MS);
      expect(postService.saveText).toHaveBeenLastCalledWith('post_01', ['the final text, again']);
      expect(track).toHaveBeenCalledWith('text_undone', { step: 'edit' });
      expect(track).toHaveBeenCalledWith('text_redone', { step: 'edit' });
    });

    it('undoes with ⌘Z and redoes with ⇧⌘Z while editing', async () => {
      renderPost(postWith('the final text'));
      const box = await postBox();
      fireEvent.change(box, { target: { value: 'the final text!' } });

      fireEvent.keyDown(box, { key: 'z', metaKey: true });
      expect(box).toHaveValue('the final text');

      fireEvent.keyDown(box, { key: 'z', metaKey: true, shiftKey: true });
      expect(box).toHaveValue('the final text!');
    });

    it('says newer rewrites are in history when typing drops them from redo', async () => {
      vi.mocked(postService.addVersion).mockResolvedValue(TWO[1]!);
      renderPost(draft([TWO[0]!]));
      await sendFeedback('Punchier hook');
      await boxHolds('the second text');
      fireEvent.click(button('Undo'));
      await boxHolds('the first text');

      fireEvent.change(await postBox(), { target: { value: 'the first text, mine' } });

      expect(await card().findByText('Newer rewrites are in history')).toBeInTheDocument();
      expect(button('Redo')).toBeDisabled();
      expect(track).toHaveBeenCalledWith('redo_rewrites_dropped', { count: 1 });
      await pause(5_000);
      expect(card().queryByText('Newer rewrites are in history')).not.toBeInTheDocument();

      fireEvent.click(button('History'));
      const history = within(await screen.findByRole('dialog', { name: 'History' }));
      expect(history.getByRole('button', { name: /^Version 2/ })).toBeInTheDocument();
    });

    it('marks the words that changed in Pumpkin, scrolled into view, until they fade', async () => {
      renderPost(postWith('Ship it today'));
      const box = await postBox();
      fireEvent.change(box, { target: { value: 'Ship it early today' } });
      fireEvent.click(button('Undo'));

      fireEvent.click(button('Redo'));

      const mark = (await textCard()).getByText('early', { selector: 'mark' });
      expect(mark.scrollIntoView).toHaveBeenCalled();
      await pause(1_300);
      expect((await textCard()).queryByText('early', { selector: 'mark' })).not.toBeInTheDocument();
    });

    it('shows the marks without a fade for a while with reduced motion', async () => {
      const matchMedia = vi.spyOn(window, 'matchMedia').mockImplementation(
        (query: string) =>
          ({
            matches: query === '(prefers-reduced-motion: reduce)',
            media: query,
            addEventListener: () => {},
            removeEventListener: () => {},
          }) as unknown as MediaQueryList,
      );
      renderPost(postWith('Ship it today'));
      const box = await postBox();
      fireEvent.change(box, { target: { value: 'Ship it early today' } });
      fireEvent.click(button('Undo'));
      fireEvent.click(button('Redo'));

      await pause(1_300);
      expect((await textCard()).getByText('early', { selector: 'mark' })).toBeInTheDocument();
      await pause(300);
      expect((await textCard()).queryByText('early', { selector: 'mark' })).not.toBeInTheDocument();
      matchMedia.mockRestore();
    });

    it('offers no undo on a Scheduled Post', async () => {
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();

      expect(card().queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
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
      const send = panel('Draft').getByRole('button', { name: 'Send feedback' });
      await waitFor(() => expect(send).toBeEnabled());
      fireEvent.click(send);
    }

    it('offers a Feedback composer with the Format, a send arrow and "Post to…"', async () => {
      renderPost(postWith('the final text'));
      await textCard();

      const dock = panel('Draft');
      expect(feedbackBox()).toHaveAttribute('placeholder', 'What should change?');
      expect(dock.getByRole('radio', { name: 'Single post' })).toBeChecked();
      expect(dock.getByRole('button', { name: 'Send feedback' })).toBeDisabled();
      expect(await card().findByRole('button', { name: 'Post to…' })).toBeInTheDocument();
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
      expect(card().getByText('Writing version 2 from your feedback…')).toBeInTheDocument();
      expect(screen.getByRole('article', { name: 'Text' })).toHaveAttribute('aria-busy', 'true');
      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'make it shorter', 'post', [
        'the first final',
      ]);
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'feedback' });

      answer(versionTwo);

      expect((await textCard()).getByText('the second final')).toBeInTheDocument();
      expect(
        await card().findByRole('button', { name: 'V2 · From feedback: “make it shorter”' }),
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

      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'expand it', 'thread', [
        'the first final',
      ]);
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

    it('moves the Format to the Text’s when a restore changes it', async () => {
      const versions = [version(1, ['the first text']), version(2, ['part one', 'part two'])];
      vi.mocked(postService.restoreVersion).mockResolvedValue(textOf(versions[0]!));
      renderPost(draft(versions));
      await textCard();
      const format = within(panel('Draft').getByRole('radiogroup', { name: 'Format' }));
      expect(format.getByRole('radio', { name: 'Thread' })).toBeChecked();

      fireEvent.click(card().getByRole('button', { name: 'History' }));
      const history = within(await screen.findByRole('dialog', { name: 'History' }));
      fireEvent.click(history.getByRole('button', { name: /^Version 1/ }));

      await waitFor(() => expect(format.getByRole('radio', { name: 'Single post' })).toBeChecked());
      vi.mocked(postService.addVersion).mockResolvedValue(version(3, ['the third text']));
      await sendFeedback('shorter');
      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'shorter', 'post', [
        'the first text',
      ]);
    });

    it('shows a failure in the dock with a way to try again, keeping the Feedback', async () => {
      vi.mocked(postService.addVersion)
        .mockRejectedValueOnce(apiError(502, 'Writing the post failed. Please try again.'))
        .mockResolvedValueOnce(versionTwo);
      renderPost(postWith('the first final'));
      await textCard();

      await sendFeedback('make it shorter');

      const dock = panel('Draft');
      expect(await dock.findByRole('alert')).toHaveTextContent(
        'Writing the post failed. Please try again.',
      );
      expect(feedbackBox()).toHaveValue('make it shorter');
      expect(track).toHaveBeenCalledWith('post_version_failed', { kind: 'feedback' });

      fireEvent.click(dock.getByRole('button', { name: 'Try again' }));

      expect(await (await textCard()).findByText('the second final')).toBeInTheDocument();
      expect(postService.addVersion).toHaveBeenLastCalledWith(
        'post_01',
        'make it shorter',
        'post',
        ['the first final'],
      );
      expect(dock.queryByRole('alert')).not.toBeInTheDocument();
    });

    it.each([
      [404, 'Post not found.'],
      [409, 'This post is scheduled, so it takes no feedback.'],
    ])('does not count a refusal with a %i as a failed version', async (status, detail) => {
      vi.mocked(postService.addVersion).mockRejectedValue(apiError(status, detail));
      renderPost(postWith('the first final'));
      await textCard();

      await sendFeedback('make it shorter');

      expect(await panel('Draft').findByRole('alert')).toHaveTextContent(detail);
      expect(track).not.toHaveBeenCalledWith('post_version_failed', expect.anything());
    });

    it('says when the User can send Feedback again once they reach the hourly limit', async () => {
      vi.mocked(postService.addVersion).mockRejectedValue(
        apiError(429, "You've made 30 attempts at a version in the last hour.", {
          retry_at: new Date(2026, 9, 6, 15, 42).toISOString(),
        }),
      );
      renderPost(postWith('the first final'));
      await textCard();

      await sendFeedback('make it shorter');

      expect(
        await panel('Draft').findByText(
          "You've made 30 attempts at a version in the last hour. You can write again at 3:42 PM.",
        ),
      ).toHaveAttribute('role', 'status');
      expect(feedbackBox()).toHaveValue('make it shorter');
    });

    it('shows the Allowance refusal in place of the error banner', async () => {
      vi.mocked(postService.addVersion).mockRejectedValue(
        allowanceUsedUp(
          "You've used this period's 500 generations. They reset on 14 November. Failed attempts don't count.",
        ),
      );
      renderPost(postWith('the first final'));
      await textCard();

      await sendFeedback('make it shorter');

      expect(
        await panel('Draft').findByText(
          "You've used this period's 500 generations. They reset on 14 November. Failed attempts don't count.",
        ),
      ).toBeInTheDocument();
      expect(panel('Draft').queryByRole('alert')).not.toBeInTheDocument();
      expect(feedbackBox()).toHaveValue('make it shorter');
      expect(track).toHaveBeenCalledWith('allowance_used_up', { ran_out: 'generations' });
    });

    it('says how many generations are left under Send feedback once less than 10% is left', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({ generations: { limit: 500, used: 457, left: 43 } }),
      );
      renderPost(postWith('the first final'));
      await textCard();

      expect(
        await panel('Draft').findByText('43 generations left until 14 November'),
      ).toBeInTheDocument();
    });

    it('counts the generation a Feedback used in the low warning', async () => {
      vi.mocked(usageService.get)
        .mockResolvedValueOnce(usageWith({ generations: { limit: 500, used: 457, left: 43 } }))
        .mockResolvedValue(usageWith({ generations: { limit: 500, used: 458, left: 42 } }));
      vi.mocked(postService.addVersion).mockResolvedValue(version(2, ['shorter']));
      renderPost(postWith('the first final'));
      await textCard();
      await panel('Draft').findByText('43 generations left until 14 November');

      await sendFeedback('make it shorter');

      expect(
        await panel('Draft').findByText('42 generations left until 14 November'),
      ).toBeInTheDocument();
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
        expect(dock.getByRole('button', { name: 'Send feedback' })).toBeEnabled(),
      );

      fireEvent.change(feedbackBox(), { target: { value: 'a'.repeat(100_003) } });
      expect(dock.getByText('3 characters over the 100,000 limit')).toBeInTheDocument();
      expect(dock.getByRole('button', { name: 'Send feedback' })).toBeDisabled();
    });

    it.each([
      ['Enter', {}],
      ['⌘Enter', { metaKey: true }],
      ['Ctrl+Enter', { ctrlKey: true }],
    ])('sends Feedback with %s', async (_name, keys) => {
      vi.mocked(postService.addVersion).mockResolvedValue(versionTwo);
      renderPost(postWith('the first final'));
      await textCard();
      fireEvent.change(feedbackBox(), { target: { value: 'make it shorter' } });
      await waitFor(() =>
        expect(panel('Draft').getByRole('button', { name: 'Send feedback' })).toBeEnabled(),
      );

      fireEvent.keyDown(feedbackBox(), { key: 'Enter', ...keys });

      await waitFor(() =>
        expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'make it shorter', 'post', [
          'the first final',
        ]),
      );
    });

    it('leaves Shift+Enter alone, so it adds a newline instead of sending Feedback', async () => {
      renderPost(postWith('the first final'));
      await textCard();
      fireEvent.change(feedbackBox(), { target: { value: 'make it shorter' } });
      await waitFor(() =>
        expect(panel('Draft').getByRole('button', { name: 'Send feedback' })).toBeEnabled(),
      );

      const shiftEnter = fireEvent.keyDown(feedbackBox(), { key: 'Enter', shiftKey: true });

      expect(shiftEnter).toBe(true);
      expect(postService.addVersion).not.toHaveBeenCalled();
    });

    it.each([
      ['while composing', { isComposing: true }],
      ['right after composing, as Safari sends it', { keyCode: 229 }],
    ])(
      'does not send Feedback with an Enter that picks an IME candidate %s',
      async (_when, ime) => {
        vi.mocked(postService.addVersion).mockResolvedValue(versionTwo);
        renderPost(postWith('the first final'));
        await textCard();
        fireEvent.change(feedbackBox(), { target: { value: 'もっと短く' } });
        await waitFor(() =>
          expect(panel('Draft').getByRole('button', { name: 'Send feedback' })).toBeEnabled(),
        );

        fireEvent.keyDown(feedbackBox(), { key: 'Enter', ...ime });

        expect(panel('Draft').getByRole('button', { name: 'Send feedback' })).toBeEnabled();
        expect(feedbackBox()).toHaveValue('もっと短く');
      },
    );

    it('keeps typed Feedback in the box after "Post to…"', async () => {
      renderPost(postWith('the first final'));
      await textCard();

      fireEvent.change(feedbackBox(), { target: { value: 'keep me' } });
      fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }));
      await dialogClosed();

      expect(feedbackBox()).toHaveValue('keep me');
    });
  });

  describe('Scheduled', () => {
    beforeEach(() => {
      // Before SCHEDULED's time, so it isn't posting yet; timers run on so reads come back.
      vi.useFakeTimers({ shouldAdvanceTime: true });
      vi.setSystemTime(new Date('2026-10-10T12:00:00Z'));
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    /** What the publisher's work shows on the next reads of the Post, each a new answer. */
    function readsBack(scheduledPost: ScheduledPost) {
      vi.mocked(postService.get).mockImplementation(async () =>
        withScheduledPost({ ...scheduledPost }),
      );
    }

    it('shows Posting… once it is due, and the Published Post once the publisher is through', async () => {
      vi.setSystemTime(new Date('2026-10-12T07:00:30Z'));
      renderPost(withScheduledPost({ ...SCHEDULED, posting: true }));
      await textCard();
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      readsBack({ ...SCHEDULED, state: 'publishing', posting: true });

      await act(() => vi.advanceTimersByTimeAsync(5_000));
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      readsBack({
        ...SCHEDULED,
        state: 'published',
        publishedAt: '2026-10-12T07:01:10Z',
        xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
      });

      await act(() => vi.advanceTimersByTimeAsync(30_000));
      expect(await screen.findByRole('region', { name: 'Published' })).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts / Published');
    });

    it('shows Posting…, then the Failed Post with its reason and the X connection read again', async () => {
      vi.setSystemTime(new Date('2026-10-12T07:00:30Z'));
      renderPost(withScheduledPost({ ...SCHEDULED, state: 'publishing', posting: true }));
      await textCard();
      await waitFor(() => expect(xConnectionService.get).toHaveBeenCalled());
      vi.mocked(xConnectionService.get).mockClear();
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      readsBack({
        ...SCHEDULED,
        state: 'failed',
        failedReason: 'X refused the post: duplicate content.',
      });

      await act(() => vi.advanceTimersByTimeAsync(30_000));
      expect(
        await panel('Failed').findByText('X refused the post: duplicate content.'),
      ).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts / Failed');
      expect(xConnectionService.get).toHaveBeenCalled();
    });

    it('turns to Posting… when its time comes while the page is open', async () => {
      vi.setSystemTime(new Date('2026-10-12T06:59:50Z'));
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();
      expect(
        panel('Scheduled').getByText('Scheduled for Mon, Oct 12, 9:00 AM'),
      ).toBeInTheDocument();
      expect(announcedPosting()).not.toBeInTheDocument();

      await act(() => vi.advanceTimersByTimeAsync(10_000));

      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      expect(announcedPosting()).toBeInTheDocument();
    });

    it('offers Edit while X was busy and it waits for its retry, and Posting… once the retry is due', async () => {
      vi.setSystemTime(new Date('2026-10-12T07:01:30Z'));
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();
      expect(await panel('Scheduled').findByRole('button', { name: 'Edit' })).toBeInTheDocument();
      readsBack({ ...SCHEDULED, posting: true });

      await act(() => vi.advanceTimersByTimeAsync(3_000));

      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      expect(panel('Scheduled').queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    });

    it('closes the editor once posting starts, announcing it in the same live region', async () => {
      vi.setSystemTime(new Date('2026-10-12T06:59:50Z'));
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();
      fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
      expect(
        await screen.findByRole('region', { name: 'Edit the scheduled post' }),
      ).toBeInTheDocument();
      const region = liveRegion();
      expect(region).toBeEmptyDOMElement();

      await act(() => vi.advanceTimersByTimeAsync(10_000));

      expect(
        screen.queryByRole('region', { name: 'Edit the scheduled post' }),
      ).not.toBeInTheDocument();
      expect(liveRegion()).toBe(region);
      expect(region).toHaveTextContent('Posting…');
    });

    it('says the editor closed while posting, and not again on a later retry', async () => {
      vi.setSystemTime(new Date('2026-10-12T06:59:50Z'));
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();
      fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
      await screen.findByRole('region', { name: 'Edit the scheduled post' });
      readsBack({ ...SCHEDULED, state: 'publishing', posting: true });

      await act(() => vi.advanceTimersByTimeAsync(10_000));
      await act(() => vi.advanceTimersByTimeAsync(3_000));
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      expect(panel('Scheduled').getByText(EDIT_CLOSED)).toBeInTheDocument();
      expect(panel('Scheduled').queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();

      // X was busy: back in scheduled, waiting for its retry.
      readsBack(SCHEDULED);
      await act(() => vi.advanceTimersByTimeAsync(5_000));
      expect(
        screen.queryByRole('region', { name: 'Edit the scheduled post' }),
      ).not.toBeInTheDocument();
      expect(panel('Scheduled').queryByText(EDIT_CLOSED)).not.toBeInTheDocument();
      expect(panel('Scheduled').getByRole('button', { name: 'Edit' })).toBeInTheDocument();

      readsBack({ ...SCHEDULED, posting: true });
      await act(() => vi.advanceTimersByTimeAsync(10_000));
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      expect(panel('Scheduled').queryByText(EDIT_CLOSED)).not.toBeInTheDocument();
    });

    it('turns to Posting… when its time comes after the editor was cancelled', async () => {
      vi.setSystemTime(new Date('2026-10-12T06:59:50Z'));
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();
      fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
      const editor = within(await screen.findByRole('region', { name: 'Edit the scheduled post' }));
      fireEvent.click(editor.getByRole('button', { name: 'Cancel' }));
      await panel('Scheduled').findByRole('button', { name: 'Edit' });

      await act(() => vi.advanceTimersByTimeAsync(10_000));

      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      expect(panel('Scheduled').queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    });

    it.each([
      [
        'failed',
        'Failed',
        { ...SCHEDULED, state: 'failed', failedReason: 'X refused the post.' },
        "This post failed while you were editing, so your changes weren't saved.",
      ],
      [
        'was published',
        'Published',
        { ...SCHEDULED, state: 'published', publishedAt: '2026-10-12T07:01:40Z' },
        "This post was published while you were editing, so your changes weren't saved.",
      ],
    ] as const)(
      'says the editor closed because the post %s',
      async (_what, dock, read, message) => {
        // X was busy: Edit is offered while its retry waits, and reads go on.
        vi.setSystemTime(new Date('2026-10-12T07:01:30Z'));
        renderPost(withScheduledPost(SCHEDULED));
        await textCard();
        fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
        await screen.findByRole('region', { name: 'Edit the scheduled post' });
        const region = liveRegion();
        readsBack(read);

        await act(() => vi.advanceTimersByTimeAsync(3_000));

        expect(await panel(dock).findByText(message)).toBeInTheDocument();
        expect(liveRegion()).toBe(region);
        expect(region).toHaveTextContent(message);
      },
    );

    it('says nothing of unsaved changes when a save in flight as posting starts goes through', async () => {
      vi.setSystemTime(new Date('2026-10-12T06:59:50Z'));
      let answer: (saved: ScheduledPost) => void = () => {};
      vi.mocked(scheduledPostService.edit).mockReturnValue(
        new Promise((resolve) => (answer = resolve)),
      );
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();
      fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
      const editor = within(await screen.findByRole('region', { name: 'Edit the scheduled post' }));
      fireEvent.change(screen.getByRole('textbox', { name: 'Post text' }), {
        target: { value: 'the final text, edited' },
      });
      fireEvent.click(editor.getByRole('button', { name: 'Save changes' }));
      await waitFor(() => expect(scheduledPostService.edit).toHaveBeenCalled());

      await act(() => vi.advanceTimersByTimeAsync(10_000));
      expect(panel('Scheduled').getByText(EDIT_CLOSED)).toBeInTheDocument();

      await act(async () =>
        answer({
          ...SCHEDULED,
          parts: [{ ...SCHEDULED.parts[0], text: 'the final text, edited' }],
          posting: true,
        }),
      );

      expect(panel('Scheduled').queryByText(EDIT_CLOSED)).not.toBeInTheDocument();
      expect(liveRegion()).not.toHaveTextContent(EDIT_CLOSED);
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
    });

    it('shows the post is gone once it is deleted while posting, and keeps reading after other failures', async () => {
      vi.setSystemTime(new Date('2026-10-12T07:00:30Z'));
      renderPost(withScheduledPost({ ...SCHEDULED, posting: true }));
      await textCard();
      vi.mocked(postService.get)
        .mockClear()
        .mockRejectedValue(apiError(500, 'Internal Server Error'));

      await act(() => vi.advanceTimersByTimeAsync(3_000));
      await act(() => vi.advanceTimersByTimeAsync(5_000));
      expect(postService.get).toHaveBeenCalledTimes(2);
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      vi.mocked(postService.get).mockRejectedValue(apiError(404, 'Post not found.'));

      await act(() => vi.advanceTimersByTimeAsync(10_000));
      await act(() => vi.advanceTimersByTimeAsync(60_000));
      expect(postService.get).toHaveBeenCalledTimes(3);
      expect(screen.getByText(/This post isn.t here/)).toBeInTheDocument();
      expect(screen.queryByText('Posting…')).not.toBeInTheDocument();
    });

    it('says when and where it goes out, with Edit and no Feedback', async () => {
      renderPost(withScheduledPost(SCHEDULED));
      await textCard();

      const dock = panel('Scheduled');
      expect(dock.getByText('Scheduled for Mon, Oct 12, 9:00 AM')).toBeInTheDocument();
      expect(dock.getByText('Your profile')).toBeInTheDocument();
      expect(card().getByRole('button', { name: /^V2 · From feedback/ })).toBeInTheDocument();
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

    afterEach(() => {
      vi.useRealTimers();
    });

    beforeEach(() => {
      // Before SCHEDULED's time, so it isn't posting yet.
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(new Date('2026-10-10T12:00:00Z'));
      vi.mocked(scheduledPostService.edit).mockReset();
      vi.mocked(scheduledPostService.cancel).mockReset();
      vi.mocked(scheduledPostService.pastCommunities).mockReset().mockResolvedValue([]);
      vi.mocked(scheduledPostService.lookUpCommunity).mockReset();
    });

    async function startEditing(scheduledPost: ScheduledPost = SCHEDULED) {
      renderPost(withScheduledPost(scheduledPost));
      await textCard();
      fireEvent.click(await panel('Scheduled').findByRole('button', { name: 'Edit' }));
      return within(await screen.findByRole('region', { name: 'Edit the scheduled post' }));
    }

    it('turns the Parts into text boxes and saves the edited text', async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...SCHEDULED,
        parts: [{ text: 'the edited text', live: false, xPostUrl: null, media: [] }],
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
          { text: 'Live one.', live: true, xPostUrl: 'https://x.com/i/web/status/1', media: [] },
          { text: 'Two.', live: false, xPostUrl: null, media: [] },
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
      renderPost(withScheduledPost({ ...SCHEDULED, state: 'publishing', posting: true }));
      await textCard();

      expect(panel('Scheduled').queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    });

    it('opens on the editor when it comes from Edit on the Posts page', async () => {
      vi.mocked(postService.get).mockResolvedValue(withScheduledPost(SCHEDULED));
      renderSignedIn('/posts/post_01', { state: { edit: true } });

      expect(
        await screen.findByRole('region', { name: 'Edit the scheduled post' }),
      ).toBeInTheDocument();
      expect((await textCard()).getByRole('textbox', { name: 'Post text' })).toHaveValue(
        'the final text',
      );
    });

    it('opens on the Post, not the editor, when Edit on the Posts page meets it posting', async () => {
      vi.setSystemTime(new Date('2026-10-12T07:00:30Z'));
      vi.mocked(postService.get).mockResolvedValue(
        withScheduledPost({ ...SCHEDULED, posting: true }),
      );
      renderSignedIn('/posts/post_01', { state: { edit: true } });

      await textCard();

      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      expect(
        screen.queryByRole('region', { name: 'Edit the scheduled post' }),
      ).not.toBeInTheDocument();
    });

    it('clears the request to edit once the editor is open, so a reload shows the Post', async () => {
      vi.mocked(postService.get).mockResolvedValue(withScheduledPost(SCHEDULED));
      renderSignedIn('/posts/post_01', { state: { edit: true } });

      await screen.findByRole('region', { name: 'Edit the scheduled post' });

      await waitFor(() =>
        expect(screen.getByRole('status', { name: 'Current state' })).toHaveTextContent('null'),
      );
      expect(screen.getByRole('status', { name: 'Current path' })).toHaveTextContent(
        '/posts/post_01',
      );
      expect(screen.getByRole('region', { name: 'Edit the scheduled post' })).toBeInTheDocument();
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
          media: [],
        },
      ],
    };

    it('says when and where it was published, and links to it on X', async () => {
      renderPost(withScheduledPost(PUBLISHED));
      await textCard();

      const dock = panel('Published');
      expect(dock.getByText('Published Mon, Oct 12, 9:00 AM')).toBeInTheDocument();
      expect(dock.getByText('Your profile')).toBeInTheDocument();
      expect(card().getByRole('button', { name: /^V2 · From feedback/ })).toBeInTheDocument();
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
        dock.getByText('This post didn’t go out. It was due Mon, Oct 12, 9:00 AM.'),
      ).toBeInTheDocument();
      expect(dock.getByText('X refused the post: duplicate content.')).toBeInTheDocument();
      expect(await card().findByRole('button', { name: 'Post to…' })).toBeInTheDocument();
      fireEvent.change(dock.getByRole('textbox', { name: 'Feedback' }), {
        target: { value: 'not a duplicate' },
      });
      const send = dock.getByRole('button', { name: 'Send feedback' });
      await waitFor(() => expect(send).toBeEnabled());
      fireEvent.click(send);

      expect(await (await textCard()).findByText('the third text')).toBeInTheDocument();
      expect(
        card().getByRole('button', { name: 'V3 · From feedback: “not a duplicate”' }),
      ).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Posts / Failed /');
    });

    it('marks the Parts of a Thread already live on X, with the Text after them', async () => {
      renderPost(
        withVersions(
          withScheduledPost({
            ...FAILED,
            parts: [
              {
                text: 'Live one.',
                live: true,
                xPostUrl: 'https://x.com/i/web/status/1',
                media: [],
              },
              { text: 'Refused two.', live: false, xPostUrl: null, media: [] },
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
    async function openPostTo(
      post: PostDetail = postWith('the final text'),
      instance: Instance = SELLS_PLANS,
    ): Promise<Dialog> {
      renderPost(post, instance);
      await textCard();
      fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
      return within(await screen.findByRole('dialog', { name: 'Post to…' }));
    }

    async function pasteCommunity(dialog: Dialog, pasted: string) {
      fireEvent.click(dialog.getByRole('radio', { name: 'Community' }));
      fireEvent.change(dialog.getByLabelText('Community URL or ID'), {
        target: { value: pasted },
      });
      await vi.waitFor(() =>
        expect(dialog.queryByText('Looking up the community…')).not.toBeInTheDocument(),
      );
    }

    it('replaces Schedule and Post now with "Post to…"', async () => {
      renderPost(postWith('the final text'));
      await textCard();

      const draftPanel = panel('Draft');
      expect(await card().findByRole('button', { name: 'Post to…' })).toBeInTheDocument();
      expect(draftPanel.queryByRole('button', { name: 'Schedule' })).not.toBeInTheDocument();
      expect(draftPanel.queryByRole('button', { name: 'Post now' })).not.toBeInTheDocument();
    });

    it('names the Format, the Part count and the X account it posts as, and no version', async () => {
      const dialog = await openPostTo(threadWith([part('the first part'), part('the second')]));

      expect(dialog.getByText('Thread · 2 parts · as @ada')).toBeInTheDocument();
      expect(dialog.queryByText(/version 1/i)).not.toBeInTheDocument();
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

    function usageWithLinkPostsLeft(left: number): Usage {
      return usageWith({ linkXPosts: { limit: 10, used: 10 - left, left } });
    }

    it('says when the text contains a link and how many link posts are left', async () => {
      vi.mocked(usageService.get).mockResolvedValue(usageWithLinkPostsLeft(8));
      const dialog = await openPostTo(postWith('Read pumpkit.io today'));

      expect(
        await dialog.findByText('Contains a link: uses 1 of your 8 link posts'),
      ).toBeInTheDocument();
    });

    it('counts what is left in the period holding the chosen time', async () => {
      vi.mocked(usageService.get).mockImplementation(async (at?: string) =>
        usageWithLinkPostsLeft(at ? 2 : 8),
      );
      const dialog = await openPostTo(postWith('Read pumpkit.io today'));
      expect(
        await dialog.findByText('Contains a link: uses 1 of your 8 link posts'),
      ).toBeInTheDocument();

      scheduleAt(dialog, '2026-10-20', '09:00');

      expect(
        await dialog.findByText('Contains a link: uses 1 of your 2 link posts'),
      ).toBeInTheDocument();
      expect(usageService.get).toHaveBeenLastCalledWith('2026-10-20T07:00:00.000Z');
    });

    it('counts each part of a thread that contains a link', async () => {
      vi.mocked(usageService.get).mockResolvedValue(usageWithLinkPostsLeft(8));
      const dialog = await openPostTo(
        threadWith([part('See https://example.com'), part('No link'), part('x.com too')]),
      );

      expect(
        await dialog.findByText('Contains links: uses 2 of your 8 link posts'),
      ).toBeInTheDocument();
    });

    it('counts the link posts left in top-ups with those left this period', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({
          linkXPosts: { limit: 10, used: 10, left: 0 },
          topUps: [
            {
              generationsLeft: 250,
              xPostsLeft: 20,
              linkXPostsLeft: 3,
              expiresAt: new Date('2027-10-03T00:00:00Z'),
            },
          ],
        }),
      );
      const dialog = await openPostTo(postWith('Read pumpkit.io today'));

      expect(
        await dialog.findByText('Contains a link: uses 1 of your 3 link posts'),
      ).toBeInTheDocument();
    });

    it('says nothing about links for a text without one', async () => {
      vi.mocked(usageService.get).mockResolvedValue(usageWithLinkPostsLeft(8));
      const plain = await openPostTo(postWith('No link in this one.'));
      await vi.waitFor(() => expect(usageService.get).toHaveBeenCalled());

      expect(plain.queryByText(/Contains a link/)).not.toBeInTheDocument();
    });

    it('says how many X posts are left once less than 10% is left', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({ xPosts: { limit: 100, used: 95, left: 5 } }),
      );
      const dialog = await openPostTo(postWith('No link in this one.'));

      expect(await dialog.findByText('5 X posts left until 14 November')).toBeInTheDocument();
    });

    it('gives no low warning while a top-up has X posts left', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({
          xPosts: { limit: 100, used: 95, left: 5 },
          topUps: [
            {
              generationsLeft: 250,
              xPostsLeft: 20,
              linkXPostsLeft: 3,
              expiresAt: new Date('2027-10-03T00:00:00Z'),
            },
          ],
        }),
      );
      const dialog = await openPostTo(postWith('No link in this one.'));
      await vi.waitFor(() => expect(usageService.get).toHaveBeenCalled());

      expect(dialog.queryByText(/X posts left until/)).not.toBeInTheDocument();
    });

    it('says nothing about links on an Instance without allowances', async () => {
      const dialog = await openPostTo(postWith('Read pumpkit.io today'));
      await vi.waitFor(() => expect(usageService.get).toHaveBeenCalled());

      expect(dialog.queryByText(/Contains a link/)).not.toBeInTheDocument();
    });

    it('shows the Allowance refusal in place of the error banner', async () => {
      const refusal =
        "You've used this period's 100 X posts. They reset on 14 November. Failed posts don't count.";
      vi.mocked(scheduledPostService.schedule).mockRejectedValue(
        allowanceUsedUp(refusal, { ran_out: 'x_posts' }),
      );
      const dialog = await openPostTo();

      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      expect(await dialog.findByText(refusal)).toBeInTheDocument();
      expect(dialog.queryByRole('alert')).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('allowance_used_up', { ran_out: 'x_posts' });
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
      expect(await dialog.findByLabelText('Which community')).toHaveDisplayValue('Indie makers');
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
      fireEvent.change(dialog.getByLabelText('Which community'), {
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
          {
            text: 'the first part',
            live: true,
            xPostUrl: 'https://x.com/i/web/status/1',
            media: [],
          },
          {
            text: 'the second part',
            live: true,
            xPostUrl: 'https://x.com/i/web/status/2',
            media: [],
          },
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
      expect(dialog.getByText(/from @ada into the community/i)).toBeInTheDocument();
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

      expect(dialog.getByText('Connect your X account to post this post.')).toBeInTheDocument();
      expect(dialog.queryByRole('radio', { name: 'My profile' })).not.toBeInTheDocument();
      expect(dialog.queryByRole('radio', { name: 'Now' })).not.toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Connect X' }));
      await waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
      );
    });

    it('says posting to X is not set up on an Instance without X, offering no Connect X', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(null);
      const dialog = await openPostTo(undefined, { ...SELLS_PLANS, x_connection: false });

      expect(
        dialog.getByText("Posting to X isn't set up on this Pumpkit yet."),
      ).toBeInTheDocument();
      expect(dialog.queryByRole('button', { name: 'Connect X' })).not.toBeInTheDocument();
    });

    it('asks the User to reconnect X when X no longer accepts its access', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, needsReconnect: true });
      const dialog = await openPostTo();

      expect(dialog.getByText('Reconnect X to post this post.')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Reconnect X' })).toBeInTheDocument();
    });

    it('sends a User who is no longer Subscribed to the Paywall', async () => {
      vi.mocked(scheduledPostService.postNow).mockRejectedValue(apiError(403, 'Subscribe first.'));
      const dialog = await openPostTo();
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('opens "Post to…" on an Instance that sells no Plans', async () => {
      renderPost(postWith('the final text'), { ...SELLS_PLANS, sells_plans: false });
      await textCard();

      fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));

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
    const LIVE_ONE: ScheduledPostPart = {
      text: 'Live one.',
      live: true,
      xPostUrl: 'https://x.com/i/web/status/1',
      media: [],
    };
    /** A Thread whose Part 1 went out from Version 1 and whose Part 2 X refused. */
    const FAILED_PARTWAY: ScheduledPost = {
      ...FAILED,
      parts: [LIVE_ONE, { text: 'Refused two.', live: false, xPostUrl: null, media: [] }],
      failedReason: 'X refused part 2: Nope',
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
      fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
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
        parts: [{ text: 'the second text', live: false, xPostUrl: null, media: [] }],
      });
      const dialog = await openRetry();

      expect(dialog.getByText('Single post · 1 part · as @ada')).toBeInTheDocument();
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
        parts: [
          {
            text: 'the second text',
            live: true,
            xPostUrl: 'https://x.com/i/web/status/2',
            media: [],
          },
        ],
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

    it('shows the post as posting when Post now leaves its video to the publisher', async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...SCHEDULED,
        publishAt: '2026-10-10T10:00:00Z',
        posting: true,
        parts: [
          {
            text: 'the second text',
            live: false,
            xPostUrl: null,
            media: [
              {
                id: 'media_01',
                kind: 'video',
                previewUrl: '/media/media_01/preview',
                width: 1280,
                height: 720,
                altText: null,
                durationMs: 42_000,
              },
            ],
          },
        ],
      });
      const dialog = await openRetry();

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await dialogClosed();
      expect(scheduledPostService.edit).toHaveBeenCalledWith('scheduled_post_01', {
        copyText: true,
        community: null,
        shareWithFollowers: false,
        publishNow: true,
      });
      expect(panel('Scheduled').getByText('Posting…')).toBeInTheDocument();
      expect(screen.queryByText(/X was busy/)).not.toBeInTheDocument();
    });

    it("copies the Post's Text even when it is the text that failed", async () => {
      vi.mocked(scheduledPostService.edit).mockResolvedValue(SCHEDULED);
      renderPost(withVersions(withScheduledPost(FAILED), [version(1, ['the final text'])]));
      await textCard();

      fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
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
          { text: 'Fixed two.', live: true, xPostUrl: 'https://x.com/i/web/status/3', media: [] },
          { text: 'New three.', live: true, xPostUrl: 'https://x.com/i/web/status/4', media: [] },
        ],
      });
      const dialog = await openRetry(
        failedThread(version(2, ['Rewritten one.', 'Fixed two.', 'New three.'])),
      );

      expect(dialog.getByText('Thread · 3 parts · as @ada')).toBeInTheDocument();
      expect(
        dialog.getByText('Part 1 is already on X, so only parts 2 to 3 go out, as replies to it.'),
      ).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));

      expect(dialog.getByText(/These 2 parts go out/)).toBeInTheDocument();
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
          'Part 1 is already on X, and the text has no part after it. Ask for more parts with feedback.',
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
        apiError(409, 'Publishing has started, so this scheduled post can no longer change.'),
      );
      const dialog = await openRetry();

      scheduleAt(dialog, '2026-10-12', '09:00');
      fireEvent.click(dialog.getByRole('button', { name: /^Schedule for/ }));

      expect(
        await dialog.findByText(
          'Publishing has started, so this scheduled post can no longer change.',
        ),
      ).toBeInTheDocument();
    });

    it('sends a User who is no longer Subscribed to the Paywall', async () => {
      vi.mocked(scheduledPostService.edit).mockRejectedValue(apiError(403, 'Subscribe first.'));
      const dialog = await openRetry();
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);

      fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

      await waitFor(() => expect(currentPath()).toBe('/subscribe'));
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

    fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

    expect(await sidebar.findByRole('link', { name: 'Posts, 1 failed' })).toBeInTheDocument();
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
    expect(await sidebar.findByRole('link', { name: 'Posts, 1 failed' })).toBeInTheDocument();
    vi.mocked(postService.list).mockResolvedValue(NO_POSTS);

    fireEvent.click(await card().findByRole('button', { name: 'Post to…' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Post to…' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Review and post' }));
    fireEvent.click(dialog.getByRole('button', { name: 'Post now' }));

    expect(await sidebar.findByRole('link', { name: 'Posts' })).toBeInTheDocument();
    expect(sidebar.queryByRole('link', { name: 'Posts, 1 failed' })).not.toBeInTheDocument();
  });
});
