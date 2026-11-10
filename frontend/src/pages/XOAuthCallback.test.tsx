import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { useAuth } from '@/contexts/AuthContext';
import { XOAuthCallback } from './XOAuthCallback';

vi.mock('@/contexts/AuthContext', () => ({ useAuth: vi.fn() }));
vi.mock('./XSignInCallback', () => ({ XSignInCallback: () => <p>sign-in handler</p> }));
vi.mock('./XConnectionCallback', () => ({ XConnectionCallback: () => <p>reconnect handler</p> }));

function show(state: string, signedIn: boolean) {
  vi.mocked(useAuth).mockReturnValue({ isAuthenticated: signedIn, isLoading: false } as ReturnType<
    typeof useAuth
  >);
  render(
    <MemoryRouter initialEntries={[`/oauth/x/callback?code=bound&state=${state}`]}>
      <Routes>
        <Route path="/oauth/x/callback" element={<XOAuthCallback />} />
        <Route path="/login" element={<p>restart sign-in</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

it.each([true, false])(
  'routes a sign-in attempt independently of session presence (%s)',
  (signedIn) => {
    show('signin.bound', signedIn);
    expect(screen.getByText('sign-in handler')).toBeInTheDocument();
    expect(screen.queryByText('reconnect handler')).not.toBeInTheDocument();
  },
);
it('routes an authenticated reconnect to its own handler', () => {
  show('reconnect.bound', true);
  expect(screen.getByText('reconnect handler')).toBeInTheDocument();
});
it('requires sign-in again if a reconnect loses its session', async () => {
  show('reconnect.bound', false);
  expect(await screen.findByText('restart sign-in')).toBeInTheDocument();
  expect(screen.queryByText('sign-in handler')).not.toBeInTheDocument();
});
it.each(['unknown', ''])('requires restarting an unrecognized attempt (%s)', async (state) => {
  show(state, true);
  expect(await screen.findByText('restart sign-in')).toBeInTheDocument();
});
