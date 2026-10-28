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
const NEEDS_RECONNECT: XConnection = { ...CONNECTED, needsReconnect: true };
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

async function composer() {
  return within(await screen.findByRole('region', { name: 'Post to X' }));
}

async function publishedList() {
  return within(await screen.findByRole('region', { name: 'Published' }));
}

async function upcomingList() {
  return within(await screen.findByRole('region', { name: 'Upcoming' }));
}

async function reconnectBanner() {
  return within(await screen.findByRole('region', { name: 'Reconnect X' }));
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

  describe('On an Instance that sells no Plans', () => {
    const NO_PLANS: Instance = { ...SELLS_PLANS, sells_plans: false };

    beforeEach(() => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
    });

    it('lets a User without a Subscription Post now', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
      renderScheduled(undefined, NO_PLANS);

      const box = await composer();
      expect(await box.findByRole('button', { name: 'Post now' })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Subscribe' })).not.toBeInTheDocument();
    });
  });

  describe('Post now', () => {
    beforeEach(() => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    });

    it('publishes a typed text and lists it as Published with a link to X', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue(PUBLISHED);
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'Shipping the new onboarding today.' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      const published = await publishedList();
      expect(await published.findByText('Shipping the new onboarding today.')).toBeInTheDocument();
      expect(published.getByRole('link', { name: /view on x/i })).toHaveAttribute(
        'href',
        'https://x.com/i/web/status/1890000000000000001',
      );
      expect(scheduledPostService.postNow).toHaveBeenCalledWith(
        { parts: ['Shipping the new onboarding today.'] },
        { community: null, shareWithFollowers: false },
      );
      expect(box.getByLabelText('Post text')).toHaveValue('');
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'post',
        part_count: 1,
        source: 'typed',
        post_now: true,
        destination: 'profile',
      });
    });

    it('counts the text the way X does', async () => {
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'see pumpkit.io 日本' },
      });

      expect(box.getByText('32 / 280')).toBeInTheDocument();
    });

    it('holds back a text over the limit by X count', async () => {
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'a'.repeat(270) + ' 日本語のテ' },
      });

      expect(box.getByText('1 character over the 280 limit')).toBeInTheDocument();
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();
    });

    it('allows an X Premium account up to 25,000 by X count', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue({ ...CONNECTED, charLimit: 25_000 });
      renderScheduled();

      const box = await composer();
      const text = await box.findByLabelText('Post text');
      fireEvent.change(text, {
        target: { value: 'a'.repeat(24_976) + ' https://example.com/' + 'x'.repeat(80) },
      });

      expect(box.getByText('25,000 / 25,000')).toBeInTheDocument();
      expect(box.getByRole('button', { name: 'Post now' })).toBeEnabled();

      fireEvent.change(text, { target: { value: 'a'.repeat(24_990) + ' 日本語のテ' } });

      expect(box.getByText('1 character over the 25,000 limit')).toBeInTheDocument();
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();
    });

    it('lists a Post now that failed with its reason', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue(FAILED);
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'Shipping again.' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      const failed = within(await screen.findByRole('region', { name: 'Failed' }));
      expect(await failed.findByText('Shipping again.')).toBeInTheDocument();
      expect(failed.getByText(FAILED.failedReason!)).toBeInTheDocument();
      expect(box.getByLabelText('Post text')).toHaveValue('Shipping again.');
    });

    it('says Pumpkit will retry when X was busy and lists it as upcoming', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...PUBLISHED,
        state: 'scheduled',
        publishedAt: null,
        xPostUrl: null,
      });
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'Shipping the new onboarding today.' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      expect(await box.findByRole('status')).toHaveTextContent(
        'X was busy. Pumpkit will keep trying for the next 15 minutes.',
      );
      expect(
        await (await upcomingList()).findByText('Shipping the new onboarding today.'),
      ).toBeInTheDocument();
      expect(box.getByLabelText('Post text')).toHaveValue('');
    });

    it('shows why Post now was refused and keeps the text', async () => {
      vi.mocked(scheduledPostService.postNow).mockRejectedValue(
        apiError(422, "This post is 281 characters by X's count, over the 280 limit."),
      );
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      expect(await box.findByRole('alert')).toHaveTextContent('281 characters');
      expect(box.getByLabelText('Post text')).toHaveValue('Hello');
    });

    it('sends a User without an X connection to connect X', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(null);
      vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
        'https://x.com/i/oauth2/authorize?state=s',
      );
      renderScheduled();

      const box = await composer();
      expect(await box.findByText('Connect your X account to post.')).toBeInTheDocument();
      expect(box.queryByRole('button', { name: 'Post now' })).not.toBeInTheDocument();
      fireEvent.click(box.getByRole('button', { name: 'Connect X' }));

      await vi.waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
      );
    });

    it('asks to reconnect X when its access was revoked', async () => {
      vi.mocked(xConnectionService.get).mockResolvedValue(NEEDS_RECONNECT);
      vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
        'https://x.com/i/oauth2/authorize?state=s',
      );
      renderScheduled();

      const banner = await reconnectBanner();
      expect(banner.getByText(/x no longer accepts pumpkit's access/i)).toBeInTheDocument();
      const box = await composer();
      expect(box.queryByRole('button', { name: 'Post now' })).not.toBeInTheDocument();
      fireEvent.click(banner.getByRole('button', { name: 'Reconnect X' }));

      await vi.waitFor(() =>
        expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
      );
    });

    it('shows the reconnect state once a Post now finds the access revoked', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...FAILED,
        failedReason: "Not published: X no longer accepts Pumpkit's access to your account.",
      });
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hi' } });
      vi.mocked(xConnectionService.get).mockResolvedValue(NEEDS_RECONNECT);
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      const banner = await reconnectBanner();
      expect(banner.getByRole('button', { name: 'Reconnect X' })).toBeInTheDocument();
    });

    it('points a User who is not Subscribed to billing instead of Post now', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      renderScheduled();

      const box = await composer();
      expect(await box.findByText(/posting to x needs a subscription/i)).toBeInTheDocument();
      expect(box.queryByRole('button', { name: 'Post now' })).not.toBeInTheDocument();
    });
  });

  describe('Schedule', () => {
    beforeEach(() => {
      vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    });

    it('schedules a typed text for a time picked in the browser timezone', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([WEDNESDAY]);
      vi.mocked(scheduledPostService.schedule).mockResolvedValue(MONDAY);
      renderScheduled();

      const box = await composer();
      expect(box.getByText(/times are in your timezone, europe\/rome/i)).toBeInTheDocument();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'Monday morning.' },
      });
      fireEvent.change(box.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Schedule' }));

      const upcoming = await upcomingList();
      expect(await upcoming.findByText('Monday morning.')).toBeInTheDocument();
      expect(upcoming.getAllByRole('listitem')[0]).toHaveTextContent('Monday morning.');
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { parts: ['Monday morning.'] },
        '2026-10-12T07:00:00.000Z',
        { community: null, shareWithFollowers: false },
      );
      expect(box.getByLabelText('Post text')).toHaveValue('');
      expect(box.getByLabelText('Date and time')).toHaveValue('');
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'post',
        part_count: 1,
        source: 'typed',
        post_now: false,
        destination: 'profile',
      });
    });

    it('needs a date and time before scheduling', async () => {
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });

      expect(box.getByRole('button', { name: 'Schedule' })).toBeDisabled();
      expect(box.getByRole('button', { name: 'Post now' })).toBeEnabled();
    });

    it('shows why a time was refused and keeps the text and time', async () => {
      vi.mocked(scheduledPostService.schedule).mockRejectedValue(
        apiError(422, 'Pick a time at least a minute from now.'),
      );
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });
      fireEvent.change(box.getByLabelText('Date and time'), {
        target: { value: '2026-10-10T14:00' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Schedule' }));

      expect(await box.findByRole('alert')).toHaveTextContent(
        'Pick a time at least a minute from now.',
      );
      expect(box.getByLabelText('Post text')).toHaveValue('Hello');
      expect(box.getByLabelText('Date and time')).toHaveValue('2026-10-10T14:00');
    });

    it('says when the monthly cap resets once a month is full', async () => {
      const full =
        'You have 100 X posts in October 2026, the most for one month. ' +
        'The cap resets on November 1, 2026.';
      vi.mocked(scheduledPostService.schedule).mockRejectedValue(apiError(409, full));
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });
      fireEvent.change(box.getByLabelText('Date and time'), {
        target: { value: '2026-10-20T14:00' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Schedule' }));

      expect(await box.findByRole('alert')).toHaveTextContent(full);
      expect(box.getByLabelText('Post text')).toHaveValue('Hello');
      expect(box.getByRole('button', { name: 'Schedule' })).toBeEnabled();
    });

    it('holds back scheduling a text over the limit by X count', async () => {
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'a'.repeat(281) },
      });
      fireEvent.change(box.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });

      expect(box.getByRole('button', { name: 'Schedule' })).toBeDisabled();
    });
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

    it('schedules a Thread typed Part by Part', async () => {
      vi.mocked(scheduledPostService.schedule).mockResolvedValue(THREAD);
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'A Thread starts here.' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Add a Part' }));
      expect(box.getByLabelText('Part 1')).toHaveValue('A Thread starts here.');
      fireEvent.change(box.getByLabelText('Part 2'), { target: { value: 'And ends here.' } });
      fireEvent.change(box.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Schedule' }));

      const upcoming = await upcomingList();
      expect(await upcoming.findByText('Thread, 2 Parts')).toBeInTheDocument();
      expect(upcoming.getAllByRole('listitem')).toHaveLength(1);
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { parts: ['A Thread starts here.', 'And ends here.'] },
        '2026-10-12T07:00:00.000Z',
        { community: null, shareWithFollowers: false },
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'thread',
        part_count: 2,
        source: 'typed',
        post_now: false,
        destination: 'profile',
      });
      expect(box.getByLabelText('Post text')).toHaveValue('');
    });

    it('reorders and removes Parts', async () => {
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'One' } });
      fireEvent.click(box.getByRole('button', { name: 'Add a Part' }));
      fireEvent.change(box.getByLabelText('Part 2'), { target: { value: 'Two' } });
      fireEvent.click(box.getByRole('button', { name: 'Add a Part' }));
      fireEvent.change(box.getByLabelText('Part 3'), { target: { value: 'Three' } });

      fireEvent.click(box.getByRole('button', { name: 'Move Part 3 up' }));
      expect(box.getByLabelText('Part 2')).toHaveValue('Three');
      expect(box.getByRole('button', { name: 'Move Part 1 up' })).toBeDisabled();
      expect(box.getByRole('button', { name: 'Move Part 3 down' })).toBeDisabled();
      fireEvent.click(box.getByRole('button', { name: 'Move Part 1 down' }));
      expect(box.getByLabelText('Part 1')).toHaveValue('Three');
      fireEvent.click(box.getByRole('button', { name: 'Remove Part 2' }));
      expect(box.getByLabelText('Part 1')).toHaveValue('Three');
      expect(box.getByLabelText('Part 2')).toHaveValue('Two');
      fireEvent.click(box.getByRole('button', { name: 'Remove Part 1' }));

      expect(box.getByLabelText('Post text')).toHaveValue('Two');
      expect(box.queryByRole('button', { name: /remove part/i })).not.toBeInTheDocument();
    });

    it('counts each Part and holds back sending while one is over the limit or empty', async () => {
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Fine.' } });
      fireEvent.click(box.getByRole('button', { name: 'Add a Part' }));
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();
      fireEvent.change(box.getByLabelText('Part 2'), { target: { value: 'a'.repeat(281) } });

      expect(box.getByText('5 / 280')).toBeInTheDocument();
      expect(box.getByText('1 character over the 280 limit')).toBeInTheDocument();
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();

      fireEvent.change(box.getByLabelText('Part 2'), { target: { value: 'Fine too.' } });
      expect(box.getByRole('button', { name: 'Post now' })).toBeEnabled();
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

    async function pickCommunity(box: Awaited<ReturnType<typeof composer>>, pasted: string) {
      fireEvent.change(await box.findByLabelText('Post to'), { target: { value: 'community' } });
      fireEvent.change(box.getByLabelText('Community URL or ID'), { target: { value: pasted } });
      await vi.waitFor(() =>
        expect(box.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
      );
    }

    it('shows the name of a pasted Community and posts it with that name', async () => {
      vi.mocked(scheduledPostService.lookUpCommunity).mockResolvedValue({
        id: COMMUNITY_ID,
        name: 'Build in Public',
        url: COMMUNITY_URL,
      });
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...IN_COMMUNITY,
        community: { id: COMMUNITY_ID, name: 'Build in Public', url: COMMUNITY_URL },
      });
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'Hello Community.' },
      });
      await pickCommunity(box, COMMUNITY_URL);

      expect(box.getByRole('link', { name: 'Build in Public' })).toHaveAttribute(
        'href',
        COMMUNITY_URL,
      );
      expect(scheduledPostService.lookUpCommunity).toHaveBeenCalledWith(COMMUNITY_ID);
      expect(track).toHaveBeenCalledWith('community_looked_up', { found: true, named: true });
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));
      await vi.waitFor(() =>
        expect(scheduledPostService.postNow).toHaveBeenCalledWith(
          { parts: ['Hello Community.'] },
          {
            community: { id: COMMUNITY_ID, name: 'Build in Public' },
            shareWithFollowers: true,
          },
        ),
      );
    });

    it('holds back posting until the pasted Community is looked up', async () => {
      vi.mocked(scheduledPostService.lookUpCommunity).mockReturnValue(new Promise(() => {}));
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });
      fireEvent.change(await box.findByLabelText('Post to'), { target: { value: 'community' } });
      fireEvent.change(box.getByLabelText('Community URL or ID'), {
        target: { value: COMMUNITY_URL },
      });

      expect(await box.findByText('Looking up the Community…')).toBeInTheDocument();
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();
    });

    it('says when X has no such Community and holds back posting', async () => {
      const missing = 'X has no Community with that ID. Check the URL.';
      vi.mocked(scheduledPostService.lookUpCommunity).mockRejectedValue(apiError(404, missing));
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });
      await pickCommunity(box, COMMUNITY_URL);

      expect(box.getByText(missing)).toBeInTheDocument();
      expect(box.getByLabelText('Community URL or ID')).toHaveAttribute('aria-invalid', 'true');
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();
      expect(track).toHaveBeenCalledWith('community_looked_up', { found: false });
    });

    it('shows the Community by its ID when its name could not be looked up', async () => {
      vi.mocked(scheduledPostService.lookUpCommunity).mockRejectedValue(apiError(500, 'boom'));
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });
      await pickCommunity(box, COMMUNITY_URL);

      expect(box.getByRole('link', { name: COMMUNITY_ID })).toHaveAttribute('href', COMMUNITY_URL);
      expect(box.getByRole('button', { name: 'Post now' })).toBeEnabled();
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

    it('posts to the profile unless a Community is picked', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue(PUBLISHED);
      renderScheduled();

      const box = await composer();
      expect(await box.findByLabelText('Post to')).toHaveDisplayValue('My profile');
      expect(box.queryByLabelText('Also share with followers')).not.toBeInTheDocument();
      fireEvent.change(box.getByLabelText('Post text'), { target: { value: 'Hello' } });
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      await vi.waitFor(() =>
        expect(scheduledPostService.postNow).toHaveBeenCalledWith(
          { parts: ['Hello'] },
          {
            community: null,
            shareWithFollowers: false,
          },
        ),
      );
    });

    it('posts now into a Community pasted by its URL, shared with followers by default', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue(IN_COMMUNITY);
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'Hello Community.' },
      });
      await pickCommunity(box, `${COMMUNITY_URL}?s=20`);
      expect(box.getByLabelText('Also share with followers')).toBeChecked();
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      const published = await publishedList();
      expect(await published.findByText('Hello Community.')).toBeInTheDocument();
      expect(scheduledPostService.postNow).toHaveBeenCalledWith(
        { parts: ['Hello Community.'] },
        {
          community: { id: COMMUNITY_ID, name: null },
          shareWithFollowers: true,
        },
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'post',
        part_count: 1,
        source: 'typed',
        post_now: true,
        destination: 'community',
        share_with_followers: true,
      });
    });

    it('schedules into a Community named by its ID, kept from the followers', async () => {
      vi.mocked(scheduledPostService.schedule).mockResolvedValue({
        ...MONDAY,
        community: { id: '123', name: null, url: 'https://x.com/i/communities/123' },
      });
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), {
        target: { value: 'Monday morning.' },
      });
      await pickCommunity(box, ' 123 ');
      fireEvent.click(box.getByLabelText('Also share with followers'));
      fireEvent.change(box.getByLabelText('Date and time'), {
        target: { value: '2026-10-12T09:00' },
      });
      fireEvent.click(box.getByRole('button', { name: 'Schedule' }));

      const upcoming = await upcomingList();
      expect(await upcoming.findByText('Monday morning.')).toBeInTheDocument();
      expect(scheduledPostService.schedule).toHaveBeenCalledWith(
        { parts: ['Monday morning.'] },
        '2026-10-12T07:00:00.000Z',
        { community: { id: '123', name: null }, shareWithFollowers: false },
      );
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        format: 'post',
        part_count: 1,
        source: 'typed',
        post_now: false,
        destination: 'community',
        share_with_followers: false,
      });
    });

    it('shows the followers checkbox only for a Community, checked each time one is picked', async () => {
      renderScheduled();

      const box = await composer();
      await pickCommunity(box, COMMUNITY_URL);
      fireEvent.click(box.getByLabelText('Also share with followers'));
      expect(box.getByLabelText('Also share with followers')).not.toBeChecked();

      fireEvent.change(box.getByLabelText('Post to'), { target: { value: 'profile' } });
      expect(box.queryByLabelText('Also share with followers')).not.toBeInTheDocument();
      expect(box.queryByLabelText('Community URL or ID')).not.toBeInTheDocument();

      fireEvent.change(box.getByLabelText('Post to'), { target: { value: 'community' } });
      expect(box.getByLabelText('Also share with followers')).toBeChecked();
    });

    it('says when the pasted text is not a Community and holds back posting', async () => {
      renderScheduled();

      const box = await composer();
      fireEvent.change(await box.findByLabelText('Post text'), { target: { value: 'Hello' } });
      await pickCommunity(box, 'https://x.com/ada');

      expect(
        box.getByText(
          "That isn't a Community. Paste its URL from X, like https://x.com/i/communities/123, or its ID.",
        ),
      ).toBeInTheDocument();
      expect(box.getByLabelText('Community URL or ID')).toHaveAttribute('aria-invalid', 'true');
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();

      fireEvent.change(box.getByLabelText('Community URL or ID'), { target: { value: '' } });
      expect(box.queryByText(/isn't a Community/)).not.toBeInTheDocument();
      expect(box.getByRole('button', { name: 'Post now' })).toBeDisabled();
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

    function pick(box: Awaited<ReturnType<typeof composer>>, option: string) {
      const value = box.getByRole<HTMLOptionElement>('option', { name: option }).value;
      fireEvent.change(box.getByLabelText('Post to'), { target: { value } });
    }

    it('offers them below My profile, next to pasting a new one', async () => {
      renderScheduled();

      const box = await composer();
      await box.findByRole('option', { name: 'Indie makers' });

      expect(box.getAllByRole('option').map((o) => o.textContent)).toEqual([
        'My profile',
        'Indie makers',
        '123',
        'Another Community',
      ]);
    });

    it('posts into the one picked, with followers checked whatever was chosen before', async () => {
      vi.mocked(scheduledPostService.postNow).mockResolvedValue(PUBLISHED);
      renderScheduled();

      const box = await composer();
      await box.findByRole('option', { name: 'Indie makers' });
      pick(box, '123');
      fireEvent.click(box.getByLabelText('Also share with followers'));
      expect(box.getByLabelText('Also share with followers')).not.toBeChecked();
      pick(box, 'Indie makers');
      expect(box.getByLabelText('Post to')).toHaveDisplayValue('Indie makers');
      expect(box.queryByLabelText('Community URL or ID')).not.toBeInTheDocument();
      expect(box.getByLabelText('Also share with followers')).toBeChecked();
      fireEvent.change(box.getByLabelText('Post text'), { target: { value: 'Hello' } });
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      await vi.waitFor(() =>
        expect(scheduledPostService.postNow).toHaveBeenCalledWith(
          { parts: ['Hello'] },
          {
            community: { id: MAKERS.id, name: 'Indie makers' },
            shareWithFollowers: true,
          },
        ),
      );
      expect(scheduledPostService.lookUpCommunity).not.toHaveBeenCalled();
    });

    it('offers a Community just posted into without a reload', async () => {
      const NEW: Community = { id: '999', name: null, url: 'https://x.com/i/communities/999' };
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([MAKERS]);
      vi.mocked(scheduledPostService.postNow).mockResolvedValue({
        ...PUBLISHED,
        community: NEW,
      });
      renderScheduled();

      const box = await composer();
      await box.findByRole('option', { name: 'Indie makers' });
      fireEvent.change(box.getByLabelText('Post text'), { target: { value: 'Hello' } });
      fireEvent.change(box.getByLabelText('Post to'), { target: { value: 'community' } });
      fireEvent.change(box.getByLabelText('Community URL or ID'), { target: { value: '999' } });
      await vi.waitFor(() =>
        expect(box.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
      );
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([NEW, MAKERS]);
      fireEvent.click(box.getByRole('button', { name: 'Post now' }));

      expect(await box.findByRole('option', { name: '999' })).toBeInTheDocument();
    });

    it('offers a Community a post was just moved into without a reload', async () => {
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([]);
      vi.mocked(scheduledPostService.list).mockResolvedValue([MONDAY]);
      vi.mocked(scheduledPostService.edit).mockResolvedValue({ ...MONDAY, community: UNNAMED });
      renderScheduled();

      const upcoming = await upcomingList();
      const item = within((await upcoming.findByText(MONDAY.parts[0].text)).closest('li')!);
      fireEvent.click(item.getByRole('button', { name: 'Edit' }));
      const dialog = within(await screen.findByRole('dialog', { name: 'Edit Scheduled post' }));
      fireEvent.change(dialog.getByLabelText('Post to'), { target: { value: 'community' } });
      fireEvent.change(dialog.getByLabelText('Community URL or ID'), { target: { value: '123' } });
      await vi.waitFor(() =>
        expect(dialog.queryByText('Looking up the Community…')).not.toBeInTheDocument(),
      );
      vi.mocked(scheduledPostService.pastCommunities).mockResolvedValue([UNNAMED]);
      fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

      const box = await composer();
      expect(await box.findByRole('option', { name: '123' })).toBeInTheDocument();
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
