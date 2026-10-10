import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
    fetchPlans: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('@/services/inspirationAuthorService', () => ({
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
    list: vi.fn().mockResolvedValue([]),
    postNow: vi.fn(),
    schedule: vi.fn(),
  },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { AuthProvider } from '@/contexts/AuthContext';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import {
  inspirationAuthorService,
  type InspirationAuthor,
} from '@/services/inspirationAuthorService';
import { postService, type Post, type Tell, type Version } from '@/services/postService';
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import { AppLayout } from './AppLayout';
import { Home } from './Home';
import { Scheduled } from './Scheduled';

const NOT_SUBSCRIBED = {
  subscription: null,
  subscribed: false,
  maySubscribe: true,
  trialDays: null,
};
const SUBSCRIBED = {
  subscription: {
    status: 'active' as const,
    planKey: 'pumpkit_pro_monthly',
    currentPeriodEnd: null,
    cancelAtPeriodEnd: false,
  },
  subscribed: true,
  maySubscribe: false,
  trialDays: null,
};

const LEVELSIO: InspirationAuthor = {
  handle: 'levelsio',
  lastFetchedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
  postCount: 18,
};
const PAULG: InspirationAuthor = {
  handle: 'paulg',
  lastFetchedAt: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  postCount: 20,
};

/** An axios-shaped rejection carrying the backend's status and `detail`. */
function apiError(status: number, detail: string, extra: Record<string, unknown> = {}) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail, ...extra } },
  });
}

function renderHome(state?: unknown) {
  return render(
    <AuthProvider>
      <ThemeProvider>
        <MemoryRouter
          initialEntries={[{ pathname: '/home', state }]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/home" element={<Home />} />
              <Route path="/scheduled" element={<Scheduled />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </AuthProvider>,
  );
}

async function authorsPanel() {
  return within(await screen.findByRole('region', { name: 'Inspiration authors' }));
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
        draft: 'the draft text',
        final,
        finalCharCount,
        finalCharLimit: 3000,
        tells,
      },
    ],
  };
}

/** A Subscribed User with one Inspiration author, ready to write. */
async function readyToWrite() {
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
  vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
  renderHome();
  await (await authorsPanel()).findByText('@levelsio');
  const area = await writer();
  await area.findByRole('button', { name: 'Write the Post' });
  return area;
}

async function writeBrief(area: Awaited<ReturnType<typeof writer>>, brief: string) {
  fireEvent.change(area.getByLabelText('Brief'), { target: { value: brief } });
  fireEvent.click(area.getByRole('button', { name: 'Write the Post' }));
}

describe('Home', () => {
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

  it('shows the writing area under the authors panel and the user in the sidebar', async () => {
    renderHome();
    expect(await authorsPanel()).toBeTruthy();
    expect(await writer()).toBeTruthy();
    expect(screen.queryByRole('heading', { name: /welcome/i })).not.toBeInTheDocument();
    expect(screen.getAllByText('Ada Lovelace').length).toBeGreaterThan(0);
  });

  describe('Writing a Post', () => {
    it('disables writing with a prompt to add an author when the User has none', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderHome();

      const area = await writer();
      expect(
        await area.findByText('Add an Inspiration author to write a Post.'),
      ).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Write the Post' })).toBeDisabled();
    });

    it('shows a User who is not Subscribed a prompt to subscribe instead of the button', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderHome();

      const area = await writer();
      expect(await area.findByText(/writing posts needs a subscription/i)).toBeInTheDocument();
      expect(area.queryByRole('button', { name: 'Write the Post' })).not.toBeInTheDocument();
    });

    it('writes the first Version, disabling the Brief while it waits, then shows Final and Draft', async () => {
      let answer: (post: Post) => void = () => {};
      vi.mocked(postService.start).mockReturnValue(new Promise((resolve) => (answer = resolve)));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(area.getByLabelText('Brief')).toBeDisabled();
      expect(area.getByRole('button', { name: /writing/i })).toBeDisabled();
      expect(area.getByRole('status')).toHaveTextContent(/writing your post/i);
      expect(postService.start).toHaveBeenCalledWith('ship small things');
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'brief' });

      answer(postWith('the final text'));

      const final = within(await area.findByRole('article', { name: 'Final' }));
      expect(final.getByText('the final text')).toBeInTheDocument();
      expect(final.getByText('14 / 3,000 characters')).toBeInTheDocument();
      expect(final.queryByText(/characters over/i)).not.toBeInTheDocument();
      const draft = within(area.getByRole('article', { name: 'Draft' }));
      expect(draft.getByText('the draft text')).toBeInTheDocument();
      expect(
        area
          .getByRole('article', { name: 'Final' })
          .compareDocumentPosition(area.getByRole('article', { name: 'Draft' })) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    });

    it('flags a Final over 3,000 characters', async () => {
      vi.mocked(postService.start).mockResolvedValue(postWith('x'.repeat(3012)));
      const area = await readyToWrite();

      await writeBrief(area, 'ship');

      const final = within(await area.findByRole('article', { name: 'Final' }));
      expect(final.getByText('3,012 / 3,000 characters')).toBeInTheDocument();
      expect(final.getByText("12 characters over X's 3,000-character limit")).toBeInTheDocument();
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
      expect(postService.start).toHaveBeenNthCalledWith(2, 'ship small things');
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
      text: 'the final text',
      state: 'scheduled',
      publishAt: '2026-10-12T07:00:00Z',
      publishedAt: null,
      xPostUrl: null,
      failedReason: null,
      createdAt: '2026-10-10T12:00:00Z',
    };

    beforeEach(() => {
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
        'the final text',
        '2026-10-12T07:00:00.000Z',
        'version_attempt_01',
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        source: 'final',
        post_now: false,
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
        'the final text',
        'version_attempt_01',
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        source: 'final',
        post_now: true,
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
      expect(dialog.queryByRole('link', { name: 'View on X' })).not.toBeInTheDocument();
    });

    it("refuses a Final over X's limit by X's count", async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      const final = await finalWritten('a'.repeat(290));

      fireEvent.click(final.getByRole('button', { name: 'Post now' }));

      const dialog = within(await screen.findByRole('dialog', { name: 'Post this Final now?' }));
      expect(dialog.getByText('10 characters over the 280 limit')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Post now' })).toBeDisabled();
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
      draft: 'the second draft',
      final: 'the second final',
      finalCharCount: 16,
      finalCharLimit: 3000,
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
      expect(postService.addVersion).toHaveBeenCalledWith('post_01', 'make it shorter');
      expect(track).toHaveBeenCalledWith('post_version_requested', { kind: 'feedback' });

      answer(versionTwo);

      const latest = within(await area.findByRole('region', { name: 'Version 2' }));
      expect(latest.getByText('the second final')).toBeInTheDocument();
      expect(latest.getByText('the second draft')).toBeInTheDocument();
      expect(latest.getByText('make it shorter')).toBeInTheDocument();
      expect(area.getByLabelText('Feedback')).toHaveValue('');
      expect(area.getByLabelText('Feedback')).toBeEnabled();
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
          final: 'the third final',
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

  describe('Sidebar', () => {
    async function withPostOnScreen() {
      vi.mocked(postService.start).mockResolvedValue(postWith('the final text'));
      const area = await readyToWrite();
      await writeBrief(area, 'ship small things');
      await area.findByText('the final text');
      return area;
    }

    function newPostShortcut(target: Element | Window = window) {
      fireEvent.keyDown(target, { key: 'O', ctrlKey: true, shiftKey: true });
    }

    it('starts a New Post from the sidebar and puts the cursor in the Brief', async () => {
      const area = await withPostOnScreen();

      const nav = within(screen.getByRole('navigation', { name: 'Main' }));
      fireEvent.click(nav.getByRole('button', { name: /new post/i }));

      expect(area.queryByText('the final text')).not.toBeInTheDocument();
      expect(area.getByLabelText('Brief')).toHaveValue('');
      expect(area.getByLabelText('Brief')).toHaveFocus();
      expect(track).toHaveBeenCalledWith('sidebar_new_post_clicked', { source: 'sidebar' });
    });

    it('keeps the Post on screen after a visit to the Scheduled page', async () => {
      await withPostOnScreen();

      const nav = within(screen.getByRole('navigation', { name: 'Main' }));
      fireEvent.click(nav.getByRole('button', { name: 'Scheduled' }));
      expect(await screen.findByRole('region', { name: 'X connection' })).toBeInTheDocument();
      expect(nav.getByRole('button', { name: 'Scheduled' })).toHaveAttribute(
        'aria-current',
        'page',
      );
      fireEvent.click(nav.getByRole('button', { name: 'Home' }));

      expect(await (await writer()).findByText('the final text')).toBeInTheDocument();
    });

    it('starts a New Post from the Scheduled page back on Home', async () => {
      await withPostOnScreen();
      const nav = within(screen.getByRole('navigation', { name: 'Main' }));
      fireEvent.click(nav.getByRole('button', { name: 'Scheduled' }));
      await screen.findByRole('region', { name: 'X connection' });

      fireEvent.click(nav.getByRole('button', { name: /new post/i }));

      const area = await writer();
      expect(area.queryByText('the final text')).not.toBeInTheDocument();
      expect(area.getByLabelText('Brief')).toHaveValue('');
    });

    it('starts a New Post from the collapsed rail', async () => {
      const area = await withPostOnScreen();

      fireEvent.click(screen.getByRole('button', { name: 'Close sidebar' }));
      const rail = within(screen.getByRole('navigation', { name: 'Sidebar rail' }));
      fireEvent.click(rail.getByRole('button', { name: 'New Post' }));

      expect(area.queryByText('the final text')).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('sidebar_new_post_clicked', { source: 'rail' });
    });

    it('starts a New Post on Ctrl+Shift+O, even while typing a Brief', async () => {
      const area = await readyToWrite();
      const brief = area.getByLabelText('Brief');
      fireEvent.change(brief, { target: { value: 'half a thought' } });

      newPostShortcut(brief);

      expect(brief).toHaveValue('');
      expect(track).toHaveBeenCalledWith('sidebar_new_post_clicked', { source: 'shortcut' });
    });

    it('starts one New Post when the shortcut is held down', async () => {
      await readyToWrite();

      newPostShortcut();
      fireEvent.keyDown(window, { key: 'O', ctrlKey: true, shiftKey: true, repeat: true });

      expect(
        vi.mocked(track).mock.calls.filter(([event]) => event === 'sidebar_new_post_clicked'),
      ).toHaveLength(1);
    });

    it('leaves the Brief alone when the shortcut is pressed over a dialog', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderHome();
      const area = await writer();
      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'half a thought' } });
      fireEvent.click(await area.findByRole('button', { name: /subscribe/i }));
      await screen.findByRole('dialog');

      newPostShortcut();

      expect(area.getByLabelText('Brief')).toHaveValue('half a thought');
    });

    it('refuses a New Post while a Version is being written', async () => {
      vi.mocked(postService.start).mockReturnValue(new Promise(() => {}));
      const area = await readyToWrite();
      await writeBrief(area, 'ship small things');

      const nav = within(screen.getByRole('navigation', { name: 'Main' }));
      expect(nav.getByRole('button', { name: /new post/i })).toBeDisabled();
      newPostShortcut();

      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(track).not.toHaveBeenCalledWith('sidebar_new_post_clicked', expect.anything());
    });

    it('closes the mobile drawer after a New Post', async () => {
      await withPostOnScreen();

      fireEvent.click(screen.getByRole('button', { name: 'Open sidebar' }));
      const drawerNav = screen.getAllByRole('navigation', { name: 'Main' }).at(-1)!;
      fireEvent.click(within(drawerNav).getByRole('button', { name: /new post/i }));

      await waitFor(() =>
        expect(screen.getAllByRole('navigation', { name: 'Main' })).toHaveLength(1),
      );
    });

    it('remembers a collapsed sidebar across visits', async () => {
      const first = renderHome();
      fireEvent.click(await screen.findByRole('button', { name: 'Close sidebar' }));
      first.unmount();

      renderHome();

      await authorsPanel();
      expect(screen.queryByRole('button', { name: 'Close sidebar' })).not.toBeInTheDocument();
    });
  });

  it('opens the billing dialog after a successful checkout', async () => {
    renderHome({ checkoutStatus: 'success' });
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Billing')).toBeInTheDocument();
  });

  describe('Inspiration authors', () => {
    it('lists the authors in order with when their posts were last fetched and how many are stored', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderHome();

      const panel = await authorsPanel();
      const items = await panel.findAllByRole('listitem');
      expect(items.map((item) => within(item).getByText(/^@/).textContent)).toEqual([
        '@levelsio',
        '@paulg',
      ]);
      expect(within(items[0]).getByText('Fetched 2 hours ago · 18 posts')).toBeInTheDocument();
      expect(within(items[1]).getByText('Fetched 5 minutes ago · 20 posts')).toBeInTheDocument();
    });

    it('shows each author chip on a phone with a short last fetched time', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderHome();

      const panel = await authorsPanel();
      const items = await panel.findAllByRole('listitem');
      expect(within(items[0]).getByText('2h ago')).toHaveClass('md:hidden');
      expect(within(items[1]).getByText('5m ago')).toHaveClass('md:hidden');
    });

    it('says how to start when the User has no authors', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderHome();

      const panel = await authorsPanel();
      expect(await panel.findByText(/no inspiration authors yet/i)).toBeInTheDocument();
    });

    it('adds a handle, shows it in the list and clears the field', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.add).mockResolvedValue(LEVELSIO);
      renderHome();

      const panel = await authorsPanel();
      const field = await panel.findByLabelText('X handle');
      fireEvent.change(field, { target: { value: '@LevelsIO' } });
      fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

      expect(await panel.findByText('@levelsio')).toBeInTheDocument();
      expect(inspirationAuthorService.add).toHaveBeenCalledWith('@LevelsIO');
      expect(field).toHaveValue('');
      expect(track).toHaveBeenCalledWith('inspiration_author_added');
    });

    it.each([
      [404, "@nobody doesn't exist on X."],
      [422, '@nobody has no original posts to learn from.'],
      [409, 'You can have up to 3 Inspiration authors. Remove one to add another.'],
    ])(
      'says why a handle was refused with a %i and keeps it in the field',
      async (status, detail) => {
        vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
        vi.mocked(inspirationAuthorService.add).mockRejectedValue(apiError(status, detail));
        renderHome();

        const panel = await authorsPanel();
        const field = await panel.findByLabelText('X handle');
        fireEvent.change(field, { target: { value: 'nobody' } });
        fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

        expect(await panel.findByRole('alert')).toHaveTextContent(detail);
        expect(field).toHaveValue('nobody');
        expect(track).not.toHaveBeenCalledWith('inspiration_author_added');
      },
    );

    it('removes an author from the list', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      vi.mocked(inspirationAuthorService.remove).mockResolvedValue(undefined);
      renderHome();

      const panel = await authorsPanel();
      fireEvent.click(await panel.findByRole('button', { name: 'Remove @levelsio' }));

      await waitFor(() => expect(panel.queryByText('@levelsio')).not.toBeInTheDocument());
      expect(panel.getByText('@paulg')).toBeInTheDocument();
      expect(inspirationAuthorService.remove).toHaveBeenCalledWith('levelsio');
      expect(track).toHaveBeenCalledWith('inspiration_author_removed');
    });

    it('shows a User who is not Subscribed their authors and a prompt to subscribe that opens Billing', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      renderHome();

      const panel = await authorsPanel();
      expect(await panel.findByText('@levelsio')).toBeInTheDocument();
      expect(await panel.findByText(/needs a subscription/i)).toBeInTheDocument();
      expect(panel.queryByLabelText('X handle')).not.toBeInTheDocument();
      expect(panel.queryByRole('button', { name: 'Remove @levelsio' })).not.toBeInTheDocument();
      expect(panel.queryByRole('button', { name: 'Refresh @levelsio' })).not.toBeInTheDocument();

      fireEvent.click(panel.getByRole('button', { name: 'Subscribe' }));
      expect(await screen.findByRole('dialog')).toBeInTheDocument();
    });

    it('shows the prompt to subscribe when adding is refused with a 403', async () => {
      vi.mocked(billingService.fetchBillingMe)
        .mockResolvedValueOnce(SUBSCRIBED)
        .mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(inspirationAuthorService.add).mockRejectedValue(
        apiError(403, 'This needs a Subscription. Subscribe to continue.'),
      );
      renderHome();

      const panel = await authorsPanel();
      fireEvent.change(await panel.findByLabelText('X handle'), { target: { value: 'levelsio' } });
      fireEvent.click(panel.getByRole('button', { name: 'Add author' }));

      expect(await panel.findByRole('button', { name: 'Subscribe' })).toBeInTheDocument();
    });

    it('refreshes an author and shows its new fetch time and post count', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      vi.mocked(inspirationAuthorService.refresh).mockResolvedValue({
        handle: 'levelsio',
        lastFetchedAt: new Date().toISOString(),
        postCount: 21,
      });
      renderHome();

      const panel = await authorsPanel();
      fireEvent.click(await panel.findByRole('button', { name: 'Refresh @levelsio' }));

      expect(await panel.findByText('Fetched just now · 21 posts')).toBeInTheDocument();
      expect(inspirationAuthorService.refresh).toHaveBeenCalledWith('levelsio');
      expect(track).toHaveBeenCalledWith('inspiration_authors_refreshed');
    });

    it('says when an author can be refreshed again after a refresh within the hour', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO]);
      const retryAt = new Date(2026, 9, 6, 15, 42);
      vi.mocked(inspirationAuthorService.refresh).mockRejectedValue(
        apiError(429, '@levelsio was fetched less than an hour ago.', {
          retry_at: retryAt.toISOString(),
        }),
      );
      renderHome();

      const panel = await authorsPanel();
      fireEvent.click(await panel.findByRole('button', { name: 'Refresh @levelsio' }));

      expect(
        await panel.findByText(
          '@levelsio was fetched less than an hour ago. You can refresh it again at 3:42 PM.',
        ),
      ).toBeInTheDocument();
      expect(panel.queryByRole('alert')).not.toBeInTheDocument();
      expect(track).not.toHaveBeenCalledWith('inspiration_authors_refreshed');
    });
  });
});
