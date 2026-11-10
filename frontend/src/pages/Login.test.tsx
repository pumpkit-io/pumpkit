import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { DEFAULT_INSTANCE } from '@/lib/instance';
import { redirectTo } from '@/lib/navigation';
import { xSignInService } from '@/services/xSignInService';
import { Login } from './Login';

vi.mock('@/services/xSignInService', () => ({ xSignInService: { start: vi.fn() } }));
vi.mock('@/lib/navigation', () => ({ redirectTo: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

function show(error = '') {
  render(
    <InstanceProvider instance={DEFAULT_INSTANCE}>
      <MemoryRouter initialEntries={[`/login${error}`]}>
        <Login />
      </MemoryRouter>
    </InstanceProvider>,
  );
}

it('offers only X and explains publishing authorization', () => {
  show();
  expect(screen.getByRole('button', { name: 'Continue with X' })).toBeInTheDocument();
  expect(screen.getByText(/authorizes Pumpkit to publish/)).toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByText(/Continue with Google/)).not.toBeInTheDocument();
});

it('opens X once and disables repeated activation', async () => {
  vi.mocked(xSignInService.start).mockResolvedValue('https://x.com/authorize');
  show();
  fireEvent.click(screen.getByRole('button', { name: 'Continue with X' }));
  expect(screen.getByRole('button', { name: 'Opening X…' })).toBeDisabled();
  expect(redirectTo).not.toHaveBeenCalled();
  await vi.waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://x.com/authorize'));
  expect(xSignInService.start).toHaveBeenCalledTimes(1);
});

it('announces provider failure and permits retry', async () => {
  vi.mocked(xSignInService.start).mockRejectedValue(new Error('network unavailable'));
  show();
  fireEvent.click(screen.getByRole('button', { name: 'Continue with X' }));
  expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't open X. Try again.");
  expect(screen.getByRole('button', { name: 'Continue with X' })).toBeEnabled();
});

it('explains how to retry after missing confirmed email', () => {
  show('?error=x_email_required');
  expect(screen.getByRole('alert')).toHaveTextContent('Confirm an email address on X');
});
