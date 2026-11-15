import { StrictMode } from 'react';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';
import { session } from '@/lib/session';
import { returnTo } from '@/lib/returnTo';
import { positioningService } from '@/services/positioningService';
import { xSignInService } from '@/services/xSignInService';
import { XSignInCallback } from './XSignInCallback';

vi.mock('@/services/xSignInService', () => ({ xSignInService: { complete: vi.fn() } }));
vi.mock('@/services/positioningService', () => ({ positioningService: { startDraft: vi.fn() } }));

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
          <Route path="/oauth/consent" element={<Destination />} />
          <Route path="/login" element={<Destination />} />
        </Routes>
      </MemoryRouter>
    </StrictMode>,
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(positioningService.startDraft).mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it('announces sign-in progress and starts the existing session once before replacing history', async () => {
  const expiresAt = new Date(Date.now() + 3600_000).toISOString();
  vi.mocked(xSignInService.complete).mockResolvedValue({ accessToken: 'issued-access', expiresAt });
  callback();
  const status = screen.getByRole('status');
  expect(status).toHaveTextContent(/^Signing you in with\s*…$/);
  expect(within(status).getByRole('img', { name: 'X' })).toBeInTheDocument();
  expect(await screen.findByText('/new via REPLACE')).toBeInTheDocument();
  expect(xSignInService.complete).toHaveBeenCalledTimes(1);
  expect(xSignInService.complete).toHaveBeenCalledWith({
    code: 'valid',
    state: 'browser-state',
    error: null,
  });
  expect(session.get()).toEqual({ accessToken: 'issued-access', expiresAt });
});

it('starts the positioning draft once the session starts, signed in as the new user', async () => {
  const expiresAt = new Date(Date.now() + 3600_000).toISOString();
  vi.mocked(xSignInService.complete).mockResolvedValue({ accessToken: 'issued-access', expiresAt });
  let sessionAtStart: unknown;
  vi.mocked(positioningService.startDraft).mockImplementation(() => {
    sessionAtStart = session.get();
    return Promise.resolve();
  });

  callback();

  expect(await screen.findByText('/new via REPLACE')).toBeInTheDocument();
  expect(positioningService.startDraft).toHaveBeenCalledTimes(1);
  expect(sessionAtStart).toEqual({ accessToken: 'issued-access', expiresAt });
});

it('goes on signing in without waiting for a draft start that never answers', async () => {
  vi.mocked(xSignInService.complete).mockResolvedValue({
    accessToken: 'issued-access',
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  });
  vi.mocked(positioningService.startDraft).mockReturnValue(new Promise(() => {}));

  callback();

  expect(await screen.findByText('/new via REPLACE')).toBeInTheDocument();
});

it('goes on signing in when the draft start fails', async () => {
  vi.mocked(xSignInService.complete).mockResolvedValue({
    accessToken: 'issued-access',
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  });
  vi.mocked(positioningService.startDraft).mockRejectedValue(new Error('Network unavailable'));

  callback();

  expect(await screen.findByText('/new via REPLACE')).toBeInTheDocument();
  expect(session.get()).not.toBeNull();
});

it('resumes the validated saved destination after starting the session', async () => {
  returnTo.remember('/oauth/consent?request=pending-app');
  const expiresAt = new Date(Date.now() + 3600_000).toISOString();
  vi.mocked(xSignInService.complete).mockResolvedValue({ accessToken: 'issued-access', expiresAt });

  callback();

  expect(
    await screen.findByText('/oauth/consent?request=pending-app via REPLACE'),
  ).toBeInTheDocument();
  expect(returnTo.take()).toBeNull();
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
])('preserves pending consent through the %s refusal and a successful retry', async (detail) => {
  returnTo.remember('/oauth/consent?request=pending-app');
  vi.mocked(xSignInService.complete).mockRejectedValue({ response: { data: { detail } } });
  callback();
  expect(await screen.findByText(`/login?error=${detail} via REPLACE`)).toBeInTheDocument();
  expect(session.get()).toBeNull();
  cleanup();

  vi.mocked(xSignInService.complete).mockResolvedValue({
    accessToken: 'retry-access',
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  });
  callback('?code=retry-code&state=retry-state');

  expect(
    await screen.findByText('/oauth/consent?request=pending-app via REPLACE'),
  ).toBeInTheDocument();
  expect(returnTo.take()).toBeNull();
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

it.each([
  '?code=unbound',
  '#access_token=untrusted&token_type=Bearer&expires_at=2099-01-01T00:00:00Z',
  '#code=unbound&state=fragment-state',
])(
  'rejects an unbound callback %s without contacting the provider or starting a session',
  async (query) => {
    returnTo.remember('/oauth/consent?request=pending-app');
    callback(query);
    expect(
      await screen.findByText('/login?error=x_authorization_invalid via REPLACE'),
    ).toBeInTheDocument();
    expect(xSignInService.complete).not.toHaveBeenCalled();
    expect(session.get()).toBeNull();
    expect(returnTo.take()).toBe('/oauth/consent?request=pending-app');
  },
);

it('rejects malformed session credentials and preserves the pending consent request', async () => {
  returnTo.remember('/oauth/consent?request=pending-app');
  vi.mocked(xSignInService.complete).mockResolvedValue({
    accessToken: 'access',
    expiresAt: 'not-a-date',
  });
  callback();
  expect(await screen.findByText('/login?error=sign_in_failed via REPLACE')).toBeInTheDocument();
  expect(session.get()).toBeNull();
  expect(positioningService.startDraft).not.toHaveBeenCalled();
  expect(returnTo.take()).toBe('/oauth/consent?request=pending-app');
});

it('returns to sign-in after a network failure without storing a session', async () => {
  returnTo.remember('/oauth/consent?request=pending-app');
  vi.mocked(xSignInService.complete).mockRejectedValue(new Error('Network unavailable'));
  callback();
  expect(await screen.findByText('/login?error=x_provider_failed via REPLACE')).toBeInTheDocument();
  expect(session.get()).toBeNull();
  expect(positioningService.startDraft).not.toHaveBeenCalled();
  expect(returnTo.take()).toBe('/oauth/consent?request=pending-app');
});

it('uses only backend-issued credentials when a query callback also contains a forged fragment', async () => {
  const expiresAt = new Date(Date.now() + 3600_000).toISOString();
  vi.mocked(xSignInService.complete).mockResolvedValue({ accessToken: 'issued-access', expiresAt });

  callback('?code=valid&state=browser-state#access_token=forged&expires_at=2099-01-01T00:00:00Z');

  expect(await screen.findByText('/new via REPLACE')).toBeInTheDocument();
  expect(session.get()).toEqual({ accessToken: 'issued-access', expiresAt });
});

it('does not extend an abandoned consent destination when sign-in is retried', async () => {
  vi.useFakeTimers({ toFake: ['Date'] });
  returnTo.remember('/oauth/consent?request=pending-app');
  vi.mocked(xSignInService.complete).mockRejectedValue({
    response: { data: { detail: 'x_authorization_cancelled' } },
  });
  callback('?state=first-state&error=access_denied');
  await screen.findByText('/login?error=x_authorization_cancelled via REPLACE');
  cleanup();
  vi.setSystemTime(Date.now() + 31 * 60_000);
  vi.mocked(xSignInService.complete).mockResolvedValue({
    accessToken: 'retry-access',
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  });

  callback('?code=retry-code&state=retry-state');

  expect(await screen.findByText('/new via REPLACE')).toBeInTheDocument();
  expect(returnTo.take()).toBeNull();
});
