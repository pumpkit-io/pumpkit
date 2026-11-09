import { StrictMode } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';
import { session } from '@/lib/session';
import { xSignInService } from '@/services/xSignInService';
import { XSignInCallback } from './XSignInCallback';

vi.mock('@/services/xSignInService', () => ({ xSignInService: { complete: vi.fn() } }));

function Destination() {
  const location = useLocation();
  return <p>{`${location.pathname}${location.search} via ${useNavigationType()}`}</p>;
}

function callback(search = '?code=valid&state=browser-state') {
  render(
    <StrictMode>
      <MemoryRouter
        initialEntries={[`/oauth/x/callback${search}`]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/oauth/x/callback" element={<XSignInCallback />} />
          <Route path="/new" element={<Destination />} />
          <Route path="/login" element={<Destination />} />
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});
afterEach(cleanup);

it('announces sign-in progress and starts the existing session once before replacing history', async () => {
  const expiresAt = new Date(Date.now() + 3600_000).toISOString();
  vi.mocked(xSignInService.complete).mockResolvedValue({ accessToken: 'issued-access', expiresAt });
  callback();
  expect(screen.getByRole('status')).toHaveTextContent('Signing you in with X');
  expect(await screen.findByText('/new via REPLACE')).toBeInTheDocument();
  expect(xSignInService.complete).toHaveBeenCalledTimes(1);
  expect(xSignInService.complete).toHaveBeenCalledWith({
    code: 'valid',
    state: 'browser-state',
    error: null,
  });
  expect(session.get()).toEqual({ accessToken: 'issued-access', expiresAt });
});

it.each([
  'x_email_required',
  'x_authorization_invalid',
  'x_authorization_cancelled',
  'x_permissions_required',
  'x_provider_failed',
  'x_account_unavailable',
  'email_not_allowed',
  'account_suspended',
])('keeps the %s refusal actionable without starting a session', async (detail) => {
  vi.mocked(xSignInService.complete).mockRejectedValue({ response: { data: { detail } } });
  callback();
  expect(await screen.findByText(`/login?error=${detail} via REPLACE`)).toBeInTheDocument();
  expect(session.get()).toBeNull();
});

it('consumes a cancelled attempt through the backend without trusting its query as a session', async () => {
  vi.mocked(xSignInService.complete).mockRejectedValue({
    response: { data: { detail: 'x_authorization_cancelled' } },
  });
  callback('?state=browser-state&error=access_denied');
  expect(
    await screen.findByText('/login?error=x_authorization_cancelled via REPLACE'),
  ).toBeInTheDocument();
  expect(xSignInService.complete).toHaveBeenCalledTimes(1);
  expect(xSignInService.complete).toHaveBeenCalledWith({
    state: 'browser-state',
    code: null,
    error: 'access_denied',
  });
});

it('rejects missing state without contacting the provider or starting a session', async () => {
  callback('?code=unbound');
  expect(
    await screen.findByText('/login?error=x_authorization_invalid via REPLACE'),
  ).toBeInTheDocument();
  expect(xSignInService.complete).not.toHaveBeenCalled();
  expect(session.get()).toBeNull();
});

it('rejects malformed session credentials instead of storing them', async () => {
  vi.mocked(xSignInService.complete).mockResolvedValue({
    accessToken: 'access',
    expiresAt: 'not-a-date',
  });
  callback();
  expect(await screen.findByText('/login?error=sign_in_failed via REPLACE')).toBeInTheDocument();
  expect(session.get()).toBeNull();
});

it('returns to sign-in after a network failure without storing a session', async () => {
  vi.mocked(xSignInService.complete).mockRejectedValue(new Error('Network unavailable'));
  callback();
  expect(await screen.findByText('/login?error=x_provider_failed via REPLACE')).toBeInTheDocument();
  expect(session.get()).toBeNull();
});
