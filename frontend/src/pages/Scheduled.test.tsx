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
const CONNECTED: XConnection = { handle: 'ada', charLimit: 280, needsReconnect: false };

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

    expect(await panel.findByRole('alert')).toHaveTextContent('Server error');
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
});
