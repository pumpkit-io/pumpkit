import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/appConnectionService', () => ({
  appConnectionService: { list: vi.fn(), disconnect: vi.fn() },
}));
vi.mock('@/components/Toaster', () => ({ showToast: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { showToast } from '@/components/Toaster';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { DEFAULT_INSTANCE } from '@/lib/instance';
import { track } from '@/lib/analytics';
import { appConnectionService, type AppConnection } from '@/services/appConnectionService';
import { ConnectedAppsCard } from './ConnectedAppsCard';

const MCP_URL = 'https://pumpkit.example.org/api/v1/mcp';

function renderCard() {
  return render(
    <InstanceProvider instance={{ ...DEFAULT_INSTANCE, mcp_url: MCP_URL }}>
      <ConnectedAppsCard />
    </InstanceProvider>,
  );
}

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();

const CLAUDE: AppConnection = {
  id: 'app_connection_2',
  appName: 'Claude',
  verifiedDomain: 'claude.ai',
  createdAt: '2026-10-31T12:00:00Z',
  lastUsedAt: hoursAgo(2),
};

const CURSOR: AppConnection = {
  id: 'app_connection_1',
  appName: 'Cursor',
  verifiedDomain: null,
  createdAt: '2026-10-20T12:00:00Z',
  lastUsedAt: null,
};

function failure(status: number, detail: string) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { detail } },
  });
}

afterEach(() => vi.resetAllMocks());

describe('ConnectedAppsCard', () => {
  it('lists each connected app with whether it is verified, when it connected and when it was last used', async () => {
    vi.mocked(appConnectionService.list).mockResolvedValue([CLAUDE, CURSOR]);

    renderCard();

    const claude = await screen.findByRole('listitem', { name: 'Claude' });
    expect(within(claude).getByText('Verified: claude.ai')).toBeInTheDocument();
    expect(
      within(claude).getByText('Connected Oct 31 · last used 2 hours ago'),
    ).toBeInTheDocument();
    const cursor = screen.getByRole('listitem', { name: 'Cursor' });
    expect(within(cursor).getByText('Unverified')).toBeInTheDocument();
    expect(within(cursor).getByText('Connected Oct 20 · never used')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem').map((item) => item.getAttribute('aria-label'))).toEqual([
      'Claude',
      'Cursor',
    ]);
  });

  it('folds the URL and the how-tos behind "Add another app" once an app is connected', async () => {
    vi.mocked(appConnectionService.list).mockResolvedValue([CLAUDE]);

    renderCard();

    const toggle = await screen.findByRole('button', { name: 'Add another app' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(MCP_URL)).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(MCP_URL)).toBeInTheDocument();
    expect(screen.getByText('Claude Code')).toBeInTheDocument();
  });

  it('with no apps, shows the URL from the Instance, the how-tos and the empty state', async () => {
    vi.mocked(appConnectionService.list).mockResolvedValue([]);

    renderCard();

    expect(await screen.findByText('No apps connected yet.')).toBeInTheDocument();
    expect(screen.getByText(MCP_URL)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add another app' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Claude Code'));
    expect(
      screen.getByText(`claude mcp add --scope user --transport http pumpkit ${MCP_URL}`),
    ).toBeInTheDocument();
  });

  it('disconnects an app after a confirmation', async () => {
    vi.mocked(appConnectionService.list).mockResolvedValue([CLAUDE, CURSOR]);
    vi.mocked(appConnectionService.disconnect).mockResolvedValue();
    renderCard();
    const claude = await screen.findByRole('listitem', { name: 'Claude' });

    fireEvent.click(within(claude).getByRole('button', { name: 'Disconnect Claude' }));
    expect(appConnectionService.disconnect).not.toHaveBeenCalled();
    expect(
      within(claude).getByText('Claude stops working with Pumpkit at once.'),
    ).toBeInTheDocument();
    fireEvent.click(within(claude).getByRole('button', { name: 'Disconnect app' }));

    await waitFor(() =>
      expect(screen.queryByRole('listitem', { name: 'Claude' })).not.toBeInTheDocument(),
    );
    expect(appConnectionService.disconnect).toHaveBeenCalledWith('app_connection_2');
    expect(showToast).toHaveBeenCalledWith('Disconnected Claude.');
    expect(track).toHaveBeenCalledWith('app_disconnected');
    expect(screen.getByRole('listitem', { name: 'Cursor' })).toBeInTheDocument();
  });

  it('keeps the app connected when the confirmation is dismissed', async () => {
    vi.mocked(appConnectionService.list).mockResolvedValue([CLAUDE]);
    renderCard();
    const claude = await screen.findByRole('listitem', { name: 'Claude' });

    fireEvent.click(within(claude).getByRole('button', { name: 'Disconnect Claude' }));
    fireEvent.click(within(claude).getByRole('button', { name: 'Keep it' }));

    expect(appConnectionService.disconnect).not.toHaveBeenCalled();
    expect(within(claude).getByRole('button', { name: 'Disconnect Claude' })).toBeInTheDocument();
  });

  it('keeps the row and says why when disconnecting fails', async () => {
    vi.mocked(appConnectionService.list).mockResolvedValue([CLAUDE]);
    vi.mocked(appConnectionService.disconnect).mockRejectedValue(
      failure(404, "That app isn't connected."),
    );
    renderCard();
    const claude = await screen.findByRole('listitem', { name: 'Claude' });

    fireEvent.click(within(claude).getByRole('button', { name: 'Disconnect Claude' }));
    fireEvent.click(within(claude).getByRole('button', { name: 'Disconnect app' }));

    expect(await within(claude).findByText("That app isn't connected.")).toBeInTheDocument();
    expect(showToast).not.toHaveBeenCalled();
  });

  it('shows a skeleton while the list loads', () => {
    vi.mocked(appConnectionService.list).mockReturnValue(new Promise(() => {}));

    renderCard();

    expect(screen.getByRole('status', { name: 'Loading your connected apps' })).toBeInTheDocument();
  });

  it('offers a retry when the list fails to load', async () => {
    vi.mocked(appConnectionService.list)
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValueOnce([CLAUDE]);

    renderCard();

    expect(await screen.findByText("Couldn't load your connected apps.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('listitem', { name: 'Claude' })).toBeInTheDocument();
  });
});
