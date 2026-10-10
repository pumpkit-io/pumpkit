import { fireEvent, render, screen, within } from '@testing-library/react';
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
vi.mock('@/services/xConnectionService', () => ({
  xConnectionService: {
    get: vi.fn(),
    startAuthorization: vi.fn(),
    complete: vi.fn(),
    disconnect: vi.fn(),
  },
}));
vi.mock('@/services/scheduledPostService', () => ({
  scheduledPostService: { list: vi.fn(), postNow: vi.fn(), schedule: vi.fn() },
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
import { scheduledPostService, type ScheduledPost } from '@/services/scheduledPostService';
import { xConnectionService, type XConnection } from '@/services/xConnectionService';
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
  text: 'Shipping the new onboarding today.',
  state: 'published',
  publishAt: '2026-10-10T12:00:00Z',
  publishedAt: '2026-10-10T12:00:14Z',
  xPostUrl: 'https://x.com/i/web/status/1890000000000000001',
  failedReason: null,
  createdAt: '2026-10-10T12:00:14Z',
};
// The tests run in Europe/Rome (vitest.config.ts), two hours ahead of UTC in October.
const MONDAY: ScheduledPost = {
  id: 'scheduled_post_03',
  text: 'Monday morning.',
  state: 'scheduled',
  publishAt: '2026-10-12T07:00:00Z',
  publishedAt: null,
  xPostUrl: null,
  failedReason: null,
  createdAt: '2026-10-10T12:00:00Z',
};
const WEDNESDAY: ScheduledPost = {
  ...MONDAY,
  id: 'scheduled_post_04',
  text: 'Wednesday morning.',
  publishAt: '2026-10-14T07:00:00Z',
};
const FAILED: ScheduledPost = {
  id: 'scheduled_post_02',
  text: 'Shipping again.',
  state: 'failed',
  publishAt: '2026-10-10T12:01:00Z',
  publishedAt: null,
  xPostUrl: null,
  failedReason: 'X refused the post: You are not allowed to create a Tweet with duplicate content.',
  createdAt: '2026-10-10T12:01:03Z',
};

function apiError(status: number, detail: string) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

function renderScheduled(state?: unknown) {
  return render(
    <AuthProvider>
      <ThemeProvider>
        <MemoryRouter
          initialEntries={[{ pathname: '/scheduled', state }]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/scheduled" element={<Scheduled />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ThemeProvider>
    </AuthProvider>,
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

async function xPanel() {
  return within(await screen.findByRole('region', { name: 'X connection' }));
}

describe('Scheduled', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(xConnectionService.startAuthorization).mockReset();
    vi.mocked(xConnectionService.disconnect).mockReset();
    vi.mocked(scheduledPostService.list).mockReset().mockResolvedValue([]);
    vi.mocked(scheduledPostService.postNow).mockReset();
    vi.mocked(scheduledPostService.schedule).mockReset();
    vi.mocked(redirectTo).mockReset();
    vi.mocked(track).mockClear();
  });

  it('offers a Subscribed User without an X connection to connect X', async () => {
    vi.mocked(xConnectionService.startAuthorization).mockResolvedValue(
      'https://x.com/i/oauth2/authorize?state=s',
    );
    renderScheduled();

    const panel = await xPanel();
    fireEvent.click(await panel.findByRole('button', { name: 'Connect X' }));

    await vi.waitFor(() =>
      expect(redirectTo).toHaveBeenCalledWith('https://x.com/i/oauth2/authorize?state=s'),
    );
  });

  it('shows the connected handle with a way to disconnect it', async () => {
    vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    vi.mocked(xConnectionService.disconnect).mockResolvedValue();
    renderScheduled();

    const panel = await xPanel();
    expect(await panel.findByText('@ada')).toBeInTheDocument();
    fireEvent.click(panel.getByRole('button', { name: 'Disconnect' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Disconnect @ada?' }));
    expect(await dialog.findByText(/no scheduled posts are waiting/i)).toBeInTheDocument();
    fireEvent.click(dialog.getByRole('button', { name: 'Disconnect' }));

    expect(await panel.findByRole('button', { name: 'Connect X' })).toBeInTheDocument();
    expect(panel.queryByText('@ada')).not.toBeInTheDocument();
    expect(track).toHaveBeenCalledWith('x_disconnected');
  });

  it('keeps the X connection on screen when disconnecting fails', async () => {
    vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    vi.mocked(xConnectionService.disconnect).mockRejectedValue(apiError(500, 'Server error'));
    renderScheduled();

    const panel = await xPanel();
    fireEvent.click(await panel.findByRole('button', { name: 'Disconnect' }));
    const dialog = within(await screen.findByRole('dialog'));
    fireEvent.click(await dialog.findByRole('button', { name: 'Disconnect' }));

    expect(await panel.findByRole('alert')).toHaveTextContent('Server error');
    expect(panel.getByText('@ada')).toBeInTheDocument();
  });

  it('warns how many Scheduled posts are waiting before disconnecting', async () => {
    vi.mocked(xConnectionService.get)
      .mockResolvedValueOnce(CONNECTED)
      .mockResolvedValue({ ...CONNECTED, scheduledPostsWaiting: 3 });
    renderScheduled();

    const panel = await xPanel();
    fireEvent.click(await panel.findByRole('button', { name: 'Disconnect' }));

    const dialog = within(await screen.findByRole('dialog', { name: 'Disconnect @ada?' }));
    expect(
      await dialog.findByText(
        '3 Scheduled posts are waiting to go out on @ada. They will fail unless you connect @ada again before their time.',
      ),
    ).toBeInTheDocument();
    fireEvent.click(dialog.getByRole('button', { name: 'Keep it' }));
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(xConnectionService.disconnect).not.toHaveBeenCalled();
    expect(panel.getByText('@ada')).toBeInTheDocument();
  });

  it('shows why connecting failed to start', async () => {
    vi.mocked(xConnectionService.startAuthorization).mockRejectedValue(
      apiError(503, 'X_CLIENT_ID, X_CLIENT_SECRET and X_REDIRECT_URI must be set.'),
    );
    renderScheduled();

    const panel = await xPanel();
    fireEvent.click(await panel.findByRole('button', { name: 'Connect X' }));

    expect(await panel.findByRole('alert')).toHaveTextContent(/X_CLIENT_ID/);
    expect(redirectTo).not.toHaveBeenCalled();
  });

  it('points a User who is not Subscribed to billing instead of connecting', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
    renderScheduled();

    const panel = await xPanel();
    expect(await panel.findByText(/connecting x needs a subscription/i)).toBeInTheDocument();
    expect(panel.queryByRole('button', { name: 'Connect X' })).not.toBeInTheDocument();
    fireEvent.click(panel.getByRole('button', { name: /subscribe/i }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('lets a User who is not Subscribed still see and disconnect their X connection', async () => {
    vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(xConnectionService.get).mockResolvedValue(CONNECTED);
    renderScheduled();

    const panel = await xPanel();
    expect(await panel.findByText('@ada')).toBeInTheDocument();
    expect(panel.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();
  });

  it('shows the message the X callback left behind', async () => {
    renderScheduled({
      xConnectionNotice: 'You cancelled connecting X. Connect it whenever you like.',
    });

    const panel = await xPanel();
    expect(
      await panel.findByText('You cancelled connecting X. Connect it whenever you like.'),
    ).toBeInTheDocument();
  });

  it('says when the X connection could not be loaded', async () => {
    vi.mocked(xConnectionService.get).mockRejectedValue(apiError(500, 'boom'));
    renderScheduled();

    const panel = await xPanel();
    expect(await panel.findByRole('alert')).toHaveTextContent(/couldn't load your x connection/i);
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
        'Shipping the new onboarding today.',
      );
      expect(box.getByLabelText('Post text')).toHaveValue('');
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        source: 'typed',
        post_now: true,
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

      const panel = await xPanel();
      expect(await panel.findByText(/x no longer accepts pumpkit's access/i)).toBeInTheDocument();
      const box = await composer();
      expect(box.queryByRole('button', { name: 'Post now' })).not.toBeInTheDocument();
      fireEvent.click(panel.getByRole('button', { name: 'Reconnect X' }));

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

      const panel = await xPanel();
      expect(await panel.findByRole('button', { name: 'Reconnect X' })).toBeInTheDocument();
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
        'Monday morning.',
        '2026-10-12T07:00:00.000Z',
      );
      expect(box.getByLabelText('Post text')).toHaveValue('');
      expect(box.getByLabelText('Date and time')).toHaveValue('');
      expect(track).toHaveBeenCalledWith('scheduled_post_created', {
        source: 'typed',
        post_now: false,
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

  describe('lists', () => {
    it('shows Published ones with a link to X and Failed ones with their reason', async () => {
      vi.mocked(scheduledPostService.list).mockResolvedValue([FAILED, PUBLISHED]);
      renderScheduled();

      const published = await publishedList();
      expect(await published.findByText(PUBLISHED.text)).toBeInTheDocument();
      expect(published.getByRole('link', { name: /view on x/i })).toBeInTheDocument();
      const failed = within(await screen.findByRole('region', { name: 'Failed' }));
      expect(failed.getByText(FAILED.text)).toBeInTheDocument();
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
      expect(upcoming.queryByText(PUBLISHED.text)).not.toBeInTheDocument();
    });

    it('still shows the history to a User who is not Subscribed', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(NOT_SUBSCRIBED);
      vi.mocked(scheduledPostService.list).mockResolvedValue([PUBLISHED]);
      renderScheduled();

      const published = await publishedList();
      expect(await published.findByText(PUBLISHED.text)).toBeInTheDocument();
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
});
