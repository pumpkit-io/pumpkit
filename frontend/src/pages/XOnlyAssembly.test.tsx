import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { DEFAULT_INSTANCE } from '@/lib/instance';
import { session } from '@/lib/session';
import App from '@/App';

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(session, 'startFromFragment');
  vi.spyOn(session, 'startFromCredentials');
});
afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, '', '/');
});

it.each(['/oauth/google/callback', '/auth/magic-link/callback', '/login/magic-link/sent'])(
  'keeps the retired %s route from opening a session',
  async (path) => {
    window.history.replaceState(
      {},
      '',
      `${path}#access_token=old-token&token_type=Bearer&expires_at=2099-01-01T00:00:00Z`,
    );
    render(
      <InstanceProvider instance={DEFAULT_INSTANCE}>
        <App />
      </InstanceProvider>,
    );
    expect(await screen.findByRole('button', { name: 'Continue with X' })).toBeInTheDocument();
    expect(session.startFromFragment).not.toHaveBeenCalled();
    expect(session.startFromCredentials).not.toHaveBeenCalled();
    expect(localStorage.getItem('pumpkit:session')).toBeNull();
    expect(window.location.hash).toBe('');
  },
);
