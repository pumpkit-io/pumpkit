import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/xConnectionService', () => ({
  xConnectionService: {
    get: vi.fn(),
    startAuthorization: vi.fn(),
    complete: vi.fn(),
    disconnect: vi.fn(),
  },
}));
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn(), finish: vi.fn() },
}));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { AuthProvider } from '@/contexts/AuthContext';
import { OnboardingProvider } from '@/features/onboarding/OnboardingProvider';
import { xConnectionReturn } from '@/features/xConnection/xConnectionReturn';
import { track } from '@/lib/analytics';
import { onboardingService } from '@/services/onboardingService';
import { xConnectionService } from '@/services/xConnectionService';
import { XConnectionCallback } from './XConnectionCallback';

/** Shows where the callback navigated to, how, and the notice it left. */
function Destination() {
  const location = useLocation();
  const notice = (location.state as { xConnectionNotice?: string } | null)?.xConnectionNotice;
  return <p>{`at ${location.pathname} via ${useNavigationType()}: ${notice ?? 'no notice'}`}</p>;
}

/** Shows where the callback navigated to and what it handed Onboarding. */
function OnboardingDestination() {
  const location = useLocation();
  const arrival = (location.state as { xConnection?: unknown } | null)?.xConnection;
  return <p>{`at ${location.pathname} via ${useNavigationType()}: ${JSON.stringify(arrival)}`}</p>;
}

function renderCallback(search: string) {
  render(
    <StrictMode>
      <MemoryRouter
        initialEntries={['/settings', `/oauth/x/callback${search}`]}
        initialIndex={1}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AuthProvider>
          <OnboardingProvider initialNextStep="persona">
            <Routes>
              <Route path="/oauth/x/callback" element={<XConnectionCallback />} />
              <Route path="/settings" element={<Destination />} />
              <Route path="/posts/:id" element={<Destination />} />
              <Route path="/onboarding" element={<OnboardingDestination />} />
              <Route path="/subscribe" element={<Destination />} />
            </Routes>
          </OnboardingProvider>
        </AuthProvider>
      </MemoryRouter>
    </StrictMode>,
  );
}

function apiError(status: number, detail: string, code?: string) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail, code } },
  });
}

const ADA = {
  handle: 'ada',
  charLimit: 280,
  premium: false,
  needsReconnect: false,
  needsReconnectForMedia: false,
  scheduledPostsWaiting: 0,
  photoUrl: 'https://pbs.twimg.com/ada.jpg',
  offerPhoto: false,
};

describe('the X callback', () => {
  beforeEach(() => {
    vi.mocked(xConnectionService.complete).mockReset();
    vi.mocked(track).mockClear();
    vi.mocked(onboardingService.fetchNextStep).mockReset().mockResolvedValue(null);
  });

  it('completes the authorization once and returns to Settings', async () => {
    vi.mocked(xConnectionService.complete).mockResolvedValue({
      handle: 'ada',
      charLimit: 280,
      premium: false,
      needsReconnect: false,
      needsReconnectForMedia: false,
      scheduledPostsWaiting: 0,
      photoUrl: null,
      offerPhoto: false,
    });

    renderCallback('?state=the-state&code=the-code');

    expect(
      await screen.findByText('at /settings via REPLACE: Reconnected @ada.'),
    ).toBeInTheDocument();
    expect(xConnectionService.complete).toHaveBeenCalledTimes(1);
    expect(xConnectionService.complete).toHaveBeenCalledWith('the-code', 'the-state');
    expect(track).toHaveBeenCalledWith('x_connected');
  });

  it('returns with a message when the User cancelled X consent screen', async () => {
    renderCallback('?error=access_denied&state=the-state');

    expect(
      await screen.findByText(
        'at /settings via REPLACE: You cancelled reconnecting X. Try again when you are ready.',
      ),
    ).toBeInTheDocument();
    expect(xConnectionService.complete).not.toHaveBeenCalled();
  });

  it('returns with the reason when completing is refused', async () => {
    vi.mocked(xConnectionService.complete).mockRejectedValue(
      apiError(409, '@ada is already connected to another Pumpkit account.'),
    );

    renderCallback('?state=the-state&code=the-code');

    expect(
      await screen.findByText(
        'at /settings via REPLACE: @ada is already connected to another Pumpkit account.',
      ),
    ).toBeInTheDocument();
    expect(track).not.toHaveBeenCalledWith('x_connected');
  });

  it('keeps the expected-account error while onboarding instead of reporting ownership elsewhere', async () => {
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('persona');
    const detail = 'Reconnect the same X account, @ada. Sign out of X and retry with that account.';
    vi.mocked(xConnectionService.complete).mockRejectedValue(
      apiError(409, detail, 'X_ACCOUNT_MISMATCH'),
    );

    renderCallback('?state=the-state&code=the-code');

    expect(await screen.findByText(`at /settings via REPLACE: ${detail}`)).toBeInTheDocument();
  });

  it('returns unpaid recovery directly to the paywall with its notice', async () => {
    vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('paywall');
    vi.mocked(xConnectionService.complete).mockResolvedValue(ADA);

    renderCallback('?state=the-state&code=the-code');

    expect(
      await screen.findByText('at /subscribe via REPLACE: Reconnected @ada.'),
    ).toBeInTheDocument();
  });

  it('returns with a message when X sent neither a code nor an error', async () => {
    renderCallback('');

    expect(
      await screen.findByText(
        "at /settings via REPLACE: X didn't finish reconnecting your account. Try again.",
      ),
    ).toBeInTheDocument();
    expect(xConnectionService.complete).not.toHaveBeenCalled();
  });

  describe('after reconnecting from a Post page', () => {
    beforeEach(() => {
      xConnectionReturn.remember('/posts/post_01');
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('returns to the Post with the message', async () => {
      vi.mocked(xConnectionService.complete).mockResolvedValue(ADA);

      renderCallback('?state=the-state&code=the-code');

      expect(
        await screen.findByText('at /posts/post_01 via REPLACE: Reconnected @ada.'),
      ).toBeInTheDocument();
    });

    it('returns to the Post when the User cancelled on X', async () => {
      renderCallback('?error=access_denied&state=the-state');

      expect(
        await screen.findByText(
          'at /posts/post_01 via REPLACE: You cancelled reconnecting X. Try again when you are ready.',
        ),
      ).toBeInTheDocument();
    });

    it('returns to Settings once the saved Post page is over 30 minutes old', async () => {
      vi.useFakeTimers({ toFake: ['Date'] });
      vi.setSystemTime(Date.now() + 31 * 60 * 1000);
      vi.mocked(xConnectionService.complete).mockResolvedValue(ADA);

      renderCallback('?state=the-state&code=the-code');

      expect(
        await screen.findByText('at /settings via REPLACE: Reconnected @ada.'),
      ).toBeInTheDocument();
    });
  });
});
