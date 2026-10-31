import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
          <OnboardingProvider initialNextStep="x_connection">
            <Routes>
              <Route path="/oauth/x/callback" element={<XConnectionCallback />} />
              <Route path="/settings" element={<Destination />} />
              <Route path="/onboarding" element={<OnboardingDestination />} />
            </Routes>
          </OnboardingProvider>
        </AuthProvider>
      </MemoryRouter>
    </StrictMode>,
  );
}

function apiError(status: number, detail: string) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

const ADA = {
  handle: 'ada',
  charLimit: 280,
  needsReconnect: false,
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
      needsReconnect: false,
      scheduledPostsWaiting: 0,
      photoUrl: null,
      offerPhoto: false,
    });

    renderCallback('?state=the-state&code=the-code');

    expect(
      await screen.findByText('at /settings via REPLACE: Connected @ada.'),
    ).toBeInTheDocument();
    expect(xConnectionService.complete).toHaveBeenCalledTimes(1);
    expect(xConnectionService.complete).toHaveBeenCalledWith('the-code', 'the-state');
    expect(track).toHaveBeenCalledWith('x_connected');
  });

  it('returns with a message when the User cancelled X consent screen', async () => {
    renderCallback('?error=access_denied&state=the-state');

    expect(
      await screen.findByText(
        'at /settings via REPLACE: You cancelled connecting X. Connect it again whenever you like.',
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

  it('returns with a message when X sent neither a code nor an error', async () => {
    renderCallback('');

    expect(
      await screen.findByText(
        "at /settings via REPLACE: X didn't finish connecting your account. Try again.",
      ),
    ).toBeInTheDocument();
    expect(xConnectionService.complete).not.toHaveBeenCalled();
  });

  describe('during Onboarding', () => {
    beforeEach(() => {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('persona');
    });

    it('returns to Onboarding with the connected account', async () => {
      vi.mocked(xConnectionService.complete).mockResolvedValue(ADA);

      renderCallback('?state=the-state&code=the-code');

      expect(
        await screen.findByText(
          'at /onboarding via REPLACE: {"outcome":"connected","handle":"ada","photoUrl":"https://pbs.twimg.com/ada.jpg"}',
        ),
      ).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('x_connected');
    });

    it('returns to the X step with the reason when completing fails', async () => {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('x_connection');
      vi.mocked(xConnectionService.complete).mockRejectedValue(
        apiError(400, "X didn't give Pumpkit access to your account. Connect X again."),
      );

      renderCallback('?state=the-state&code=the-code');

      expect(
        await screen.findByText(
          'at /onboarding via REPLACE: {"outcome":"failed","reason":"X didn\'t give Pumpkit access to your account. Connect X again."}',
        ),
      ).toBeInTheDocument();
    });

    it('returns to the X step saying the account is taken', async () => {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('x_connection');
      vi.mocked(xConnectionService.complete).mockRejectedValue(
        apiError(409, '@ada is already connected to another Pumpkit account.'),
      );

      renderCallback('?state=the-state&code=the-code');

      expect(
        await screen.findByText('at /onboarding via REPLACE: {"outcome":"taken"}'),
      ).toBeInTheDocument();
    });

    it('returns to the X step when the User cancelled on X', async () => {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('x_connection');

      renderCallback('?error=access_denied&state=the-state');

      expect(
        await screen.findByText(
          'at /onboarding via REPLACE: {"outcome":"failed","reason":"You cancelled connecting X. Connect it whenever you\'re ready."}',
        ),
      ).toBeInTheDocument();
      expect(xConnectionService.complete).not.toHaveBeenCalled();
    });
  });
});
