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
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { track } from '@/lib/analytics';
import { xConnectionService } from '@/services/xConnectionService';
import { XConnectionCallback } from './XConnectionCallback';

/** Shows where the callback navigated to, how, and the notice it left. */
function Destination() {
  const location = useLocation();
  const notice = (location.state as { xConnectionNotice?: string } | null)?.xConnectionNotice;
  return <p>{`at ${location.pathname} via ${useNavigationType()}: ${notice ?? 'no notice'}`}</p>;
}

function renderCallback(search: string) {
  render(
    <StrictMode>
      <MemoryRouter
        initialEntries={['/scheduled', `/oauth/x/callback${search}`]}
        initialIndex={1}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/oauth/x/callback" element={<XConnectionCallback />} />
          <Route path="/scheduled" element={<Destination />} />
        </Routes>
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

describe('the X callback', () => {
  beforeEach(() => {
    vi.mocked(xConnectionService.complete).mockReset();
    vi.mocked(track).mockClear();
  });

  it('completes the authorization once and returns to the Scheduled page', async () => {
    vi.mocked(xConnectionService.complete).mockResolvedValue({
      handle: 'ada',
      charLimit: 280,
      needsReconnect: false,
    });

    renderCallback('?state=the-state&code=the-code');

    expect(
      await screen.findByText('at /scheduled via REPLACE: Connected @ada.'),
    ).toBeInTheDocument();
    expect(xConnectionService.complete).toHaveBeenCalledTimes(1);
    expect(xConnectionService.complete).toHaveBeenCalledWith('the-code', 'the-state');
    expect(track).toHaveBeenCalledWith('x_connected');
  });

  it('returns with a message when the User cancelled X consent screen', async () => {
    renderCallback('?error=access_denied&state=the-state');

    expect(
      await screen.findByText(
        'at /scheduled via REPLACE: You cancelled connecting X. Connect it again whenever you like.',
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
        'at /scheduled via REPLACE: @ada is already connected to another Pumpkit account.',
      ),
    ).toBeInTheDocument();
    expect(track).not.toHaveBeenCalledWith('x_connected');
  });

  it('returns with a message when X sent neither a code nor an error', async () => {
    renderCallback('');

    expect(
      await screen.findByText(
        "at /scheduled via REPLACE: X didn't finish connecting your account. Please try again.",
      ),
    ).toBeInTheDocument();
    expect(xConnectionService.complete).not.toHaveBeenCalled();
  });
});
