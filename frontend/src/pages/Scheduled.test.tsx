import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
    list: vi.fn(),
    postNow: vi.fn(),
    schedule: vi.fn(),
    edit: vi.fn(),
    cancel: vi.fn(),
    lookUpCommunity: vi.fn(),
  },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
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
  scheduledPostService,
  type Community,
  type ScheduledPost,
} from '@/services/scheduledPostService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import type { Instance } from '@/lib/instance';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { AppLayout } from './AppLayout';
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
const CONNECTED: XConnection = {
  handle: 'ada',
  charLimit: 280,
  needsReconnect: false,
  scheduledPostsWaiting: 0,
};
const PUBLISHED: ScheduledPost = {
  id: 'scheduled_post_01',
  parts: [
    {
      text: 'Shipping the new onboarding today.',
      live: true,
      xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
    },
  ],
  state: 'published',
  publishAt: '2026-10-10T12:00:00Z',
  publishedAt: '2026-10-10T12:00:14Z',
  xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
  failedReason: null,
  sourceVersionId: 'version_attempt_01',
  community: null,
  shareWithFollowers: false,
  createdAt: '2026-10-10T12:00:14Z',
};
// The tests run in Europe/Rome (vitest.config.ts), two hours ahead of UTC in October.
const MONDAY: ScheduledPost = {
  id: 'scheduled_post_03',
  parts: [{ text: 'Monday morning.', live: false, xPostUrl: null }],
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
const WEDNESDAY: ScheduledPost = {
  ...MONDAY,
  id: 'scheduled_post_04',
  parts: [{ text: 'Wednesday morning.', live: false, xPostUrl: null }],
  publishAt: '2026-10-14T07:00:00Z',
};
const FAILED: ScheduledPost = {
  id: 'scheduled_post_02',
  parts: [{ text: 'Shipping again.', live: false, xPostUrl: null }],
  state: 'failed',
  publishAt: '2026-10-10T12:01:00Z',
  publishedAt: null,
  xPostUrl: null,
  failedReason: 'X refused the post: You are not allowed to create a Tweet with duplicate content.',
  sourceVersionId: 'version_attempt_01',
  community: null,
  shareWithFollowers: false,
  createdAt: '2026-10-10T12:01:03Z',
};

function apiError(status: number, detail: string) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

function renderScheduled(state?: unknown, instance: Instance = SELLS_PLANS) {
  return render(
    <InstanceProvider instance={instance}>
      <AuthProvider>
        <ThemeProvider>
          <MemoryRouter
            initialEntries={[{ pathname: '/posts', state }]}
            future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
          >
            <Routes>
              <Route element={<AppLayout />}>
                <Route path="/posts" element={<Scheduled />} />
              </Route>
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </AuthProvider>
    </InstanceProvider>,
  );
}

async function publishedList() {
  return within(await screen.findByRole('region', { name: 'Published' }));
}

async function upcomingList() {
  return within(await screen.findByRole('region', { name: 'Upcoming' }));
}

describe('Scheduled', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    // The fixtures' times are in October 2026, so the picker's min would block them once they passed.
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-10T12:00'));
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(xConnectionService.startAuthorization).mockReset();
    vi.mocked(xConnectionService.disconnect).mockReset();
    vi.mocked(scheduledPostService.list).mockReset().mockResolvedValue([]);
    vi.mocked(scheduledPostService.postNow).mockReset();
    vi.mocked(scheduledPostService.schedule).mockReset();
    vi.mocked(scheduledPostService.edit).mockReset();
    vi.mocked(scheduledPostService.cancel).mockReset();
    // As when the Instance has no twitterapi.io: the Community comes back without a name.
    vi.mocked(scheduledPostService.lookUpCommunity)
      .mockReset()
      .mockImplementation(async (id) => ({
        id,
        name: null,
        url: `https://x.com/i/communities/${id}`,
      }));
    vi.mocked(redirectTo).mockReset();
    vi.mocked(track).mockClear();
  });

  describe('Threads', () => {
    const THREAD: ScheduledPost = {
      ...MONDAY,
      id: 'scheduled_post_05',
      parts: [
        { text: 'A Thread starts here.', live: false, xPostUrl: null },
        { text: 'And ends here.', live: false, xPostUrl: null },
      ],
    };

    beforeEach(() => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    });

    it('edits, adds and reorders the Parts of an upcoming Thread', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([THREAD]);
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...THREAD,
        parts: [
          { text: 'And ends here.', live: false, xPostUrl: null },
          { text: 'A Thread starts here!', live: false, xPostUrl: null },
          { text: 'One more.', live: false, xPostUrl: null },
        ],
      });
      renderScheduled();

      const upcoming = await upcomingList();
      fireEvent.click(
        within((await upcoming.findByText('A Thread starts here.')).closest('li')!).getByRole(
          'button',
          { name: 'Edit' },
        ),
      );
      const dialog = within(await screen.findByRole('dialog', { name: 'Edit Scheduled post' }));
      fireEvent.change(dialog.getByLabelText('Part 1'), {
        target: { value: 'A Thread starts here!' },
      });
      fireEvent.click(dialog.getByRole('button', { name: 'Move Part 2 up' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Add a Part' }));
      fireEvent.change(dialog.getByLabelText('Part 3'), { target: { value: 'One more.' } });
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

      await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(scheduledPostService.edit).toHaveBeenCalledWith(THREAD.id, {
        parts: ['And ends here.', 'A Thread starts here!', 'One more.'],
      });
      expect(await (await upcomingList()).findByText('Thread, 3 Parts')).toBeInTheDocument();
    });

    const FAILED_PARTWAY: ScheduledPost = {
      ...THREAD,
      state: 'failed',
      parts: [
        { ...THREAD.parts[0], live: true, xPostUrl: 'https://x.com/i/web/status/1' },
        THREAD.parts[1],
      ],
      failedReason: 'X refused Part 2: Duplicate content.',
      sourceVersionId: 'version_attempt_01',
    };

    it('marks the live Parts of a Thread that failed partway', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED_PARTWAY]);
      renderScheduled();

      const failedList = within(await screen.findByRole('region', { name: 'Failed' }));
      expect(
        await failedList.findByText('X refused Part 2: Duplicate content.'),
      ).toBeInTheDocument();
      expect(failedList.getByRole('link', { name: 'Part 1 is live on X' })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1',
      );
      expect(failedList.getAllByRole('link', { name: /live on X/ })).toHaveLength(1);
    });

    it('keeps the live Parts read-only and lets the others change before a reschedule', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED_PARTWAY]);
      vi.mocked(scheduledPostService.edit).mockResolvedValue({ ...THREAD, state: 'scheduled' });
      renderScheduled();

      const failedList = within(await screen.findByRole('region', { name: 'Failed' }));
      fireEvent.click(await failedList.findByRole('button', { name: 'Reschedule' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Reschedule' }));
      expect(dialog.queryByLabelText('Part 1')).not.toBeInTheDocument();
      expect(dialog.getByText('A Thread starts here.')).toBeInTheDocument();
      expect(dialog.getByRole('link', { name: 'Part 1 is live on X' })).toBeInTheDocument();
      expect(dialog.queryByRole('button', { name: 'Remove Part 1' })).not.toBeInTheDocument();
      expect(dialog.queryByRole('button', { name: 'Move Part 1 down' })).not.toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Move Part 2 up' })).toBeDisabled();
      fireEvent.change(dialog.getByLabelText('Part 2'), { target: { value: 'Fixed two.' } });
      fireEvent.click(dialog.getByRole('button', { name: 'Add a Part' }));
      fireEvent.change(dialog.getByLabelText('Part 3'), { target: { value: 'Three.' } });
      fireEvent.change(dialog.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(dialog.getByRole('button', { name: 'Reschedule' }));

      await vi.waitFor(() =>
        expect(scheduledPostService.edit).toHaveBeenCalledWith(THREAD.id, {
          parts: ['A Thread starts here.', 'Fixed two.', 'Three.'],
          publishAt: '2026-10-12T07:00:00.000Z',
        }),
      );
    });

    it('holds back a reschedule that keeps only the live Parts', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED_PARTWAY]);
      renderScheduled();

      const failedList = within(await screen.findByRole('region', { name: 'Failed' }));
      fireEvent.click(await failedList.findByRole('button', { name: 'Reschedule' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Reschedule' }));
      fireEvent.click(dialog.getByRole('button', { name: 'Remove Part 2' }));
      fireEvent.change(dialog.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });

      expect(dialog.getByRole('button', { name: 'Reschedule' })).toBeDisabled();
    });

    it('holds back saving a Thread while one of its Parts is over the limit', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([THREAD]);
      renderScheduled();

      const upcoming = await upcomingList();
      fireEvent.click(
        within((await upcoming.findByText('And ends here.')).closest('li')!).getByRole('button', {
          name: 'Edit',
        }),
      );
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.change(dialog.getByLabelText('Part 2'), { target: { value: 'a'.repeat(281) } });

      expect(dialog.getByText('1 character over the 280 limit')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled();
    });
  });

  describe('Communities', () => {
    const COMMUNITY_ID = '1493446837214187523';
    const COMMUNITY_URL = `https://x.com/i/communities/${COMMUNITY_ID}`;
    const IN_COMMUNITY: ScheduledPost = {
      ...PUBLISHED,
      id: 'scheduled_post_06',
      parts: [{ text: 'Hello Community.', live: false, xPostUrl: null }],
      community: { id: COMMUNITY_ID, name: null, url: COMMUNITY_URL },
      shareWithFollowers: true,
    };

    beforeEach(() => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    });

    it('lists a Scheduled post by its Community name', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([
        { ...MONDAY, community: { id: COMMUNITY_ID, name: 'Build in Public', url: COMMUNITY_URL } },
      ]);
      renderScheduled();

      const upcoming = await upcomingList();
      const monday = within((await upcoming.findByText('Monday morning.')).closest('li')!);
      expect(monday.getByRole('link', { name: 'Build in Public' })).toHaveAttribute(
        'href',
        COMMUNITY_URL,
      );
    });

    it('lists each one with its Community and whether a Published one went to followers', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([
        { ...MONDAY, community: IN_COMMUNITY.community, shareWithFollowers: false },
        IN_COMMUNITY,
        {
          ...PUBLISHED,
          id: 'scheduled_post_05',
          parts: [{ text: 'Only there.', live: false, xPostUrl: null }],
          community: IN_COMMUNITY.community,
        },
        PUBLISHED,
      ]);
      renderScheduled();

      const upcoming = await upcomingList();
      const monday = within((await upcoming.findByText('Monday morning.')).closest('li')!);
      expect(monday.getByRole('link', { name: COMMUNITY_ID })).toHaveAttribute(
        'href',
        COMMUNITY_URL,
      );
      expect(monday.queryByText(/followers/)).not.toBeInTheDocument();
      const published = await publishedList();
      const shared = within(published.getByText('Hello Community.').closest('li')!);
      expect(shared.getByRole('link', { name: COMMUNITY_ID })).toHaveAttribute(
        'href',
        COMMUNITY_URL,
      );
      expect(shared.getByText('Also shared with followers')).toBeInTheDocument();
      const only = within(published.getByText('Only there.').closest('li')!);
      expect(only.getByText('Not shared with followers')).toBeInTheDocument();
      const profile = within(published.getByText(PUBLISHED.parts[0].text).closest('li')!);
      expect(profile.queryByRole('link', { name: COMMUNITY_ID })).not.toBeInTheDocument();
      expect(profile.queryByText(/followers/)).not.toBeInTheDocument();
    });
  });

  describe('Past Communities', () => {
    const MAKERS: Community = {
      id: '1493446837214187523',
      name: 'Indie makers',
      url: 'https://x.com/i/communities/1493446837214187523',
    };
    const UNNAMED: Community = { id: '123', name: null, url: 'https://x.com/i/communities/123' };

    beforeEach(() => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([MAKERS, UNNAMED]);
    });

    afterEach(() => {
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([]);
    });

    it('opens the edit dialog on the post’s Community among them', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([
        { ...MONDAY, community: MAKERS, shareWithFollowers: true },
      ]);
      renderScheduled();

      const upcoming = await upcomingList();
      const item = within((await upcoming.findByText(MONDAY.parts[0].text)).closest('li')!);
      fireEvent.click(item.getByRole('button', { name: 'Edit' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Edit Scheduled post' }));
      await dialog.findByRole('option', { name: '123' });

      expect(dialog.getByLabelText('Post to')).toHaveDisplayValue('Indie makers');
      expect(dialog.getAllByRole('option', { name: 'Indie makers' })).toHaveLength(1);
      expect(dialog.queryByLabelText('Community URL or ID')).not.toBeInTheDocument();
      expect(dialog.getByLabelText('Also share with followers')).toBeChecked();
      expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled();
    });
  });

  describe('lists', () => {
    it('shows Published ones with a link to X and Failed ones with their reason', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED, PUBLISHED]);
      renderScheduled();

      const published = await publishedList();
      expect(await published.findByText(PUBLISHED.parts[0].text)).toBeInTheDocument();
      expect(published.getByRole('link', { name: /view on x/i })).toBeInTheDocument();
      const failed = within(await screen.findByRole('region', { name: 'Failed' }));
      expect(failed.getByText(FAILED.parts[0].text)).toBeInTheDocument();
      expect(failed.getByText(FAILED.failedReason!)).toBeInTheDocument();
    });

    it('shows upcoming ones soonest first with their time in the browser timezone', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([WEDNESDAY, MONDAY, PUBLISHED]);
      renderScheduled();

      const upcoming = await upcomingList();
      const items = await upcoming.findAllByRole('listitem');
      expect(items.map((item) => item.textContent)).toEqual([
        expect.stringMatching(/^Monday morning\..*Oct 12, 2026, 9:00/),
        expect.stringMatching(/^Wednesday morning\..*Oct 14, 2026, 9:00/),
      ]);
      expect(upcoming.queryByText(PUBLISHED.parts[0].text)).not.toBeInTheDocument();
    });

    it('still shows the history to a User who is not Subscribed', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(scheduledPostService.list).mockResolvedValue([PUBLISHED]);
      renderScheduled();

      const published = await publishedList();
      expect(await published.findByText(PUBLISHED.parts[0].text)).toBeInTheDocument();
    });

    it('says when nothing has been scheduled or published yet', async () => {
      renderScheduled();

      const published = await publishedList();
      expect(await published.findByText(/nothing published yet/i)).toBeInTheDocument();
      expect((await upcomingList()).getByText(/nothing scheduled/i)).toBeInTheDocument();
      expect(screen.queryByRole('region', { name: 'Failed' })).not.toBeInTheDocument();
    });

    it('says when the Scheduled posts could not be loaded', async () => {
      vi.mocked(scheduledPostService.list).mockRejectedValue(apiError(500, 'boom'));
      renderScheduled();

      const upcoming = await upcomingList();
      expect(await upcoming.findByRole('alert')).toHaveTextContent(
        /couldn't load your scheduled posts/i,
      );
    });
  });

  describe('edit, reschedule and cancel', () => {
    beforeEach(() => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    });

    async function upcomingItem(text: string) {
      const upcoming = await upcomingList();
      return within((await upcoming.findByText(text)).closest('li')!);
    }

    it('edits the text and time of an upcoming one', async () => {
      const moved = {
        ...MONDAY,
        parts: [{ text: 'Tuesday morning.', live: false, xPostUrl: null }],
        publishAt: '2026-10-13T08:00:00Z',
      };
      vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY, WEDNESDAY]);
      vi.mocked(scheduledPostService.edit).mockResolvedValue(moved);
      renderScheduled();

      fireEvent.click(
        (await upcomingItem('Monday morning.')).getByRole('button', { name: 'Edit' }),
      );
      const dialog = within(await screen.findByRole('dialog', { name: 'Edit Scheduled post' }));
      expect(dialog.getByLabelText('Post text')).toHaveValue('Monday morning.');
      expect(dialog.getByLabelText('Date and time')).toHaveValue('2026-10-12T09:00');
      fireEvent.change(dialog.getByLabelText('Post text'), {
        target: { value: 'Tuesday morning.' },
      });
      fireEvent.change(dialog.getByLabelText('Date and time'), {
        target: { value: '2026-10-13T10:00' },
      });
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

      await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(scheduledPostService.edit).toHaveBeenCalledWith(MONDAY.id, {
        parts: ['Tuesday morning.'],
        publishAt: '2026-10-13T08:00:00.000Z',
      });
      const items = (await upcomingList()).getAllByRole('listitem');
      expect(items.map((item) => item.textContent)).toEqual([
        expect.stringMatching(/^Tuesday morning\..*Oct 13, 2026, 10:00/),
        expect.stringMatching(/^Wednesday morning\./),
      ]);
    });

    it('sends only the text when the time is left as it was', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY]);
      vi.mocked(scheduledPostService.edit).mockResolvedValue({
        ...MONDAY,
        parts: [{ text: 'Fixed.', live: false, xPostUrl: null }],
      });
      renderScheduled();

      fireEvent.click(
        (await upcomingItem('Monday morning.')).getByRole('button', { name: 'Edit' }),
      );
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.change(dialog.getByLabelText('Post text'), { target: { value: 'Fixed.' } });
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

      expect(await (await upcomingList()).findByText('Fixed.')).toBeInTheDocument();
      expect(scheduledPostService.edit).toHaveBeenCalledWith(MONDAY.id, { parts: ['Fixed.'] });
    });

    it('holds back a text over the limit by X count', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY]);
      renderScheduled();

      fireEvent.click(
        (await upcomingItem('Monday morning.')).getByRole('button', { name: 'Edit' }),
      );
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.change(dialog.getByLabelText('Post text'), {
        target: { value: 'a'.repeat(281) },
      });

      expect(dialog.getByText('1 character over the 280 limit')).toBeInTheDocument();
      expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled();
    });

    it('shows why an edit was refused and reloads the list', async () => {
      const publishing = { ...MONDAY, state: 'publishing' as const };
      vi.mocked(scheduledPostService.list)
        .mockResolvedValueOnce([MONDAY])
        .mockResolvedValueOnce([publishing]);
      vi.mocked(scheduledPostService.edit).mockRejectedValue(
        apiError(409, 'Publishing has started, so this Scheduled post can no longer change.'),
      );
      renderScheduled();

      fireEvent.click(
        (await upcomingItem('Monday morning.')).getByRole('button', { name: 'Edit' }),
      );
      const dialog = within(await screen.findByRole('dialog'));
      fireEvent.change(dialog.getByLabelText('Post text'), { target: { value: 'Too late.' } });
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

      expect(await dialog.findByRole('alert')).toHaveTextContent(
        'Publishing has started, so this Scheduled post can no longer change.',
      );
      expect(dialog.getByLabelText('Post text')).toHaveValue('Too late.');
      fireEvent.click(dialog.getByRole('button', { name: 'Back' }));
      await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(await (await upcomingList()).findByText('Publishing now')).toBeInTheDocument();
    });

    it('cancels an upcoming one once the User confirms', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY, WEDNESDAY]);
      vi.mocked(scheduledPostService.cancel).mockResolvedValue(undefined);
      renderScheduled();

      fireEvent.click(
        (await upcomingItem('Monday morning.')).getByRole('button', { name: 'Cancel' }),
      );
      const dialog = within(
        await screen.findByRole('dialog', { name: 'Cancel this Scheduled post?' }),
      );
      fireEvent.click(dialog.getByRole('button', { name: 'Cancel post' }));

      await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(scheduledPostService.cancel).toHaveBeenCalledWith(MONDAY.id);
      const upcoming = await upcomingList();
      expect(upcoming.queryByText('Monday morning.')).not.toBeInTheDocument();
      expect(upcoming.getByText('Wednesday morning.')).toBeInTheDocument();
    });

    it('keeps an upcoming one when the User changes their mind', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY]);
      renderScheduled();

      fireEvent.click(
        (await upcomingItem('Monday morning.')).getByRole('button', { name: 'Cancel' }),
      );
      fireEvent.click(
        within(await screen.findByRole('dialog')).getByRole('button', { name: 'Keep it' }),
      );

      await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(scheduledPostService.cancel).not.toHaveBeenCalled();
      expect((await upcomingList()).getByText('Monday morning.')).toBeInTheDocument();
    });

    it('offers no changes to one that is publishing', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([{ ...MONDAY, state: 'publishing' }]);
      renderScheduled();

      const item = await upcomingItem('Monday morning.');
      expect(item.getByText('Publishing now')).toBeInTheDocument();
      expect(item.queryByRole('button')).not.toBeInTheDocument();
    });

    it('reschedules a Failed one, which moves back to upcoming', async () => {
      const rescheduled = {
        ...FAILED,
        state: 'scheduled' as const,
        failedReason: null,
        publishAt: '2026-10-12T07:00:00Z',
      };
      vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED]);
      vi.mocked(scheduledPostService.edit).mockResolvedValue(rescheduled);
      renderScheduled();

      const failed = within(await screen.findByRole('region', { name: 'Failed' }));
      fireEvent.click(await failed.findByRole('button', { name: 'Reschedule' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Reschedule' }));
      expect(dialog.getByLabelText('Post text')).toHaveValue(FAILED.parts[0].text);
      expect(dialog.getByLabelText('Date and time')).toHaveValue('');
      expect(dialog.getByRole('button', { name: 'Reschedule' })).toBeDisabled();
      fireEvent.change(dialog.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(dialog.getByRole('button', { name: 'Reschedule' }));

      expect(await (await upcomingList()).findByText(FAILED.parts[0].text)).toBeInTheDocument();
      expect(scheduledPostService.edit).toHaveBeenCalledWith(FAILED.id, {
        publishAt: '2026-10-12T07:00:00.000Z',
      });
      expect(screen.queryByRole('region', { name: 'Failed' })).not.toBeInTheDocument();
    });

    describe('Community', () => {
      const IN_COMMUNITY: ScheduledPost = {
        ...MONDAY,
        community: {
          id: '1493446837214187523',
          name: 'Indie makers',
          url: 'https://x.com/i/communities/1493446837214187523',
        },
        shareWithFollowers: true,
      };

      async function editDialog(text: string) {
        fireEvent.click((await upcomingItem(text)).getByRole('button', { name: 'Edit' }));
        return within(await screen.findByRole('dialog', { name: 'Edit Scheduled post' }));
      }

      it('starts from the post’s Community and moves it back to the profile', async () => {
        vi.mocked(scheduledPostService.list).mockResolvedValue([IN_COMMUNITY]);
        vi.mocked(scheduledPostService.edit).mockResolvedValue(MONDAY);
        renderScheduled();

        const dialog = await editDialog('Monday morning.');
        expect(dialog.getByLabelText('Post to')).toHaveDisplayValue('Indie makers');
        expect(dialog.queryByLabelText('Community URL or ID')).not.toBeInTheDocument();
        expect(dialog.getByLabelText('Also share with followers')).toBeChecked();
        expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled();
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'profile' } });
        expect(dialog.queryByLabelText('Also share with followers')).not.toBeInTheDocument();
        fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

        await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(scheduledPostService.edit).toHaveBeenCalledWith(MONDAY.id, { community: null });
        const item = await upcomingItem('Monday morning.');
        expect(item.queryByText(/In the Community/)).not.toBeInTheDocument();
      });

      it('moves a profile post into a pasted Community, shared with followers by default', async () => {
        vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY]);
        vi.mocked(scheduledPostService.edit).mockResolvedValue({
          ...IN_COMMUNITY,
          community: { ...IN_COMMUNITY.community!, name: null },
        });
        renderScheduled();

        const dialog = await editDialog('Monday morning.');
        expect(dialog.getByLabelText('Post to')).toHaveValue('profile');
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'community' } });
        expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled();
        fireEvent.change(dialog.getByLabelText('Community URL or ID'), {
          target: { value: IN_COMMUNITY.community!.url },
        });
        await vi.waitFor(() =>
          expect(dialog.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
        );
        expect(dialog.getByLabelText('Also share with followers')).toBeChecked();
        fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

        await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(scheduledPostService.edit).toHaveBeenCalledWith(MONDAY.id, {
          community: { id: IN_COMMUNITY.community!.id, name: null },
          shareWithFollowers: true,
        });
        expect(
          (await upcomingItem('Monday morning.')).getByRole('link', {
            name: IN_COMMUNITY.community!.id,
          }),
        ).toHaveAttribute('href', IN_COMMUNITY.community!.url);
      });

      it('shows the stored Community name and saves a text edit without looking it up', async () => {
        vi.mocked(scheduledPostService.list).mockResolvedValue([IN_COMMUNITY]);
        vi.mocked(scheduledPostService.edit).mockResolvedValue({
          ...IN_COMMUNITY,
          parts: [{ text: 'Edited.', live: false, xPostUrl: null }],
        });
        renderScheduled();

        const dialog = await editDialog('Monday morning.');
        expect(dialog.getByLabelText('Post to')).toHaveDisplayValue('Indie makers');
        fireEvent.change(dialog.getByLabelText('Post text'), { target: { value: 'Edited.' } });
        fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

        await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(scheduledPostService.edit).toHaveBeenCalledWith(MONDAY.id, { parts: ['Edited.'] });
        expect(scheduledPostService.lookUpCommunity).not.toHaveBeenCalled();
      });

      it('changes only whether it is shared with followers, keeping the Community', async () => {
        vi.mocked(scheduledPostService.list).mockResolvedValue([IN_COMMUNITY]);
        vi.mocked(scheduledPostService.edit).mockResolvedValue({
          ...IN_COMMUNITY,
          shareWithFollowers: false,
        });
        renderScheduled();

        const dialog = await editDialog('Monday morning.');
        fireEvent.click(dialog.getByLabelText('Also share with followers'));
        fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

        await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(scheduledPostService.edit).toHaveBeenCalledWith(MONDAY.id, {
          shareWithFollowers: false,
        });
      });

      it('moves a Failed one into a Community as it reschedules it', async () => {
        vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED]);
        vi.mocked(scheduledPostService.edit).mockResolvedValue({
          ...FAILED,
          state: 'scheduled',
          failedReason: null,
          publishAt: '2026-10-12T07:00:00Z',
          community: { id: '123', name: null, url: 'https://x.com/i/communities/123' },
        });
        renderScheduled();

        const failed = within(await screen.findByRole('region', { name: 'Failed' }));
        fireEvent.click(await failed.findByRole('button', { name: 'Reschedule' }));
        const dialog = within(await screen.findByRole('dialog', { name: 'Reschedule' }));
        fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'community' } });
        fireEvent.change(dialog.getByLabelText('Community URL or ID'), {
          target: { value: '123' },
        });
        await vi.waitFor(() =>
          expect(dialog.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
        );
        fireEvent.click(dialog.getByLabelText('Also share with followers'));
        expect(dialog.getByRole('button', { name: 'Reschedule' })).toBeDisabled();
        fireEvent.change(dialog.getByLabelText('Date and time'), {
          target: { value: '2026-10-12T09:00' },
        });
        fireEvent.click(dialog.getByRole('button', { name: 'Reschedule' }));

        expect(await (await upcomingList()).findByText(FAILED.parts[0].text)).toBeInTheDocument();
        expect(scheduledPostService.edit).toHaveBeenCalledWith(FAILED.id, {
          publishAt: '2026-10-12T07:00:00.000Z',
          community: { id: '123', name: null },
          shareWithFollowers: false,
        });
      });
    });

    it('removes a Failed one once the User confirms', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED]);
      vi.mocked(scheduledPostService.cancel).mockResolvedValue(undefined);
      renderScheduled();

      const failed = within(await screen.findByRole('region', { name: 'Failed' }));
      fireEvent.click(await failed.findByRole('button', { name: 'Remove' }));
      const dialog = within(
        await screen.findByRole('dialog', { name: 'Remove this Failed post?' }),
      );
      fireEvent.click(dialog.getByRole('button', { name: 'Remove' }));

      await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(scheduledPostService.cancel).toHaveBeenCalledWith(FAILED.id);
      expect(screen.queryByRole('region', { name: 'Failed' })).not.toBeInTheDocument();
    });

    it('offers no changes to a User who is not Subscribed', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY, FAILED]);
      renderScheduled();

      expect((await upcomingItem('Monday morning.')).queryByRole('button')).not.toBeInTheDocument();
      const failed = within(await screen.findByRole('region', { name: 'Failed' }));
      expect(failed.queryByRole('button')).not.toBeInTheDocument();
    });
  });
});
