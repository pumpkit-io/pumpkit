import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/apiKeyService', () => ({
  apiKeyService: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
}));

import { MemoryRouter } from 'react-router-dom';
import { SubscribedContext } from '@/features/billing/SubscribedProvider';
import { apiKeyService, type ApiKey } from '@/services/apiKeyService';
import { ApiKeysSection } from './ApiKeysSection';

const checkPaywall = vi.fn();

function renderSection() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <SubscribedContext.Provider value={{ planName: null, refresh: checkPaywall }}>
        <ApiKeysSection />
      </SubscribedContext.Provider>
    </MemoryRouter>,
  );
}

const WORK_LAPTOP: ApiKey = {
  id: 'api_key_1',
  name: 'Work laptop',
  prefix: 'pumpkit_AbCd1234',
  createdAt: '2026-10-01T09:00:00Z',
  lastUsedAt: '2026-10-12T18:30:00Z',
};

const HOME_DESKTOP: ApiKey = {
  id: 'api_key_2',
  name: 'Home desktop',
  prefix: 'pumpkit_ZyXw9876',
  createdAt: '2026-10-16T08:00:00Z',
  lastUsedAt: null,
};

const SECRET = 'pumpkit_ZyXw9876-the-rest-of-the-secret-abcdefghijk';
const COMMAND = `claude mcp add --scope user --transport http pumpkit https://pumpkit.example/api/v1/mcp --header "Authorization: Bearer ${SECRET}"`;

function failure(status: number, detail: string) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: { detail } },
  });
}

const writeText = vi.fn();

beforeEach(() => {
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
});

afterEach(() => vi.resetAllMocks());

async function createKey(name: string) {
  fireEvent.change(screen.getByLabelText('Key name'), { target: { value: name } });
  fireEvent.click(screen.getByRole('button', { name: 'Create key' }));
}

describe('ApiKeysSection', () => {
  it('lists the User’s keys with their prefix and dates', async () => {
    vi.mocked(apiKeyService.list).mockResolvedValue([WORK_LAPTOP, HOME_DESKTOP]);

    renderSection();

    const work = await screen.findByRole('listitem', { name: 'Work laptop' });
    expect(within(work).getByText('pumpkit_AbCd1234…')).toBeInTheDocument();
    expect(
      within(work).getByText(
        `Created ${new Date(WORK_LAPTOP.createdAt).toLocaleDateString()} · Last used ${new Date(
          WORK_LAPTOP.lastUsedAt!,
        ).toLocaleDateString()}`,
      ),
    ).toBeInTheDocument();
    const home = screen.getByRole('listitem', { name: 'Home desktop' });
    expect(within(home).getByText(/Never used/)).toBeInTheDocument();
  });

  it('says so when there are no keys yet', async () => {
    vi.mocked(apiKeyService.list).mockResolvedValue([]);

    renderSection();

    expect(await screen.findByText(/No API keys yet/)).toBeInTheDocument();
  });

  it('shows the secret and the command once after creating a key, each with a copy button', async () => {
    vi.mocked(apiKeyService.list).mockResolvedValue([WORK_LAPTOP]);
    vi.mocked(apiKeyService.create).mockResolvedValue({
      apiKey: HOME_DESKTOP,
      secret: SECRET,
      claudeCommand: COMMAND,
    });
    renderSection();
    await screen.findByRole('listitem', { name: 'Work laptop' });

    await createKey('  Home desktop ');

    expect(apiKeyService.create).toHaveBeenCalledWith('Home desktop');
    expect(await screen.findByText(SECRET)).toBeInTheDocument();
    expect(screen.getByText(COMMAND)).toBeInTheDocument();
    expect(screen.getByText(/won’t be shown again/)).toBeInTheDocument();
    expect(screen.getByRole('listitem', { name: 'Home desktop' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Copy key' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SECRET));
    fireEvent.click(screen.getByRole('button', { name: 'Copy command' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(COMMAND));

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
    expect(screen.queryByText(COMMAND)).not.toBeInTheDocument();
  });

  it('turns Copied back into Copy after two seconds', async () => {
    vi.mocked(apiKeyService.list).mockResolvedValue([]);
    vi.mocked(apiKeyService.create).mockResolvedValue({
      apiKey: HOME_DESKTOP,
      secret: SECRET,
      claudeCommand: COMMAND,
    });
    renderSection();
    await screen.findByText(/No API keys yet/);
    await createKey('Home desktop');
    const copyKey = await screen.findByRole('button', { name: 'Copy key' });

    vi.useFakeTimers();
    try {
      await act(async () => fireEvent.click(copyKey));
      expect(copyKey).toHaveTextContent(/^Copied$/);
      act(() => vi.advanceTimersByTime(1999));
      expect(copyKey).toHaveTextContent(/^Copied$/);
      act(() => vi.advanceTimersByTime(1));
      expect(copyKey).toHaveTextContent(/^Copy$/);
    } finally {
      vi.useRealTimers();
    }
  });

  it('revokes a key after the User confirms', async () => {
    vi.mocked(apiKeyService.list).mockResolvedValue([WORK_LAPTOP, HOME_DESKTOP]);
    vi.mocked(apiKeyService.revoke).mockResolvedValue(undefined);
    renderSection();
    const work = await screen.findByRole('listitem', { name: 'Work laptop' });

    fireEvent.click(within(work).getByRole('button', { name: 'Revoke Work laptop' }));
    expect(apiKeyService.revoke).not.toHaveBeenCalled();
    fireEvent.click(within(work).getByRole('button', { name: 'Revoke key' }));

    await waitFor(() =>
      expect(screen.queryByRole('listitem', { name: 'Work laptop' })).not.toBeInTheDocument(),
    );
    expect(apiKeyService.revoke).toHaveBeenCalledWith('api_key_1');
    expect(screen.getByRole('listitem', { name: 'Home desktop' })).toBeInTheDocument();
  });

  it('shows the backend’s message when the User already holds 10 keys', async () => {
    vi.mocked(apiKeyService.list).mockResolvedValue([WORK_LAPTOP]);
    const atCap =
      'You already have 10 API keys, the most you can hold. Revoke one to create another.';
    vi.mocked(apiKeyService.create).mockRejectedValue(failure(409, atCap));
    renderSection();
    await screen.findByRole('listitem', { name: 'Work laptop' });

    await createKey('Eleventh');

    expect(await screen.findByRole('alert')).toHaveTextContent(atCap);
    expect(screen.queryByText(/won’t be shown again/)).not.toBeInTheDocument();
  });

  it('checks the Paywall again when creating a key is refused for want of a Subscription', async () => {
    vi.mocked(apiKeyService.list).mockResolvedValue([]);
    vi.mocked(apiKeyService.create).mockRejectedValue(
      failure(403, 'This needs a subscription. Subscribe to continue.'),
    );
    renderSection();
    await screen.findByText(/No API keys yet/);

    await createKey('Work laptop');

    await waitFor(() => expect(checkPaywall).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says when the keys couldn’t be loaded', async () => {
    vi.mocked(apiKeyService.list).mockRejectedValue(new Error('Network Error'));

    renderSection();

    expect(await screen.findByText(/Couldn't load your API keys/)).toBeInTheDocument();
  });
});
