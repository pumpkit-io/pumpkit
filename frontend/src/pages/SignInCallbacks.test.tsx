import { cleanup, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';

vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analyticsConsent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analyticsConsent')>()),
  resetPostHog: vi.fn(),
}));

import { session } from '@/lib/session';
import { storage } from '@/lib/storage';
import { AuthProvider } from '@/contexts/AuthContext';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { GoogleAuthCallback } from '@/components/google/GoogleAuthCallback';
import { MagicLinkCallback } from './MagicLinkCallback';

/** Shows where the callback navigated to and whether it pushed or replaced. */
function Destination() {
  const location = useLocation();
  return <p>{`at ${location.pathname}${location.search} via ${useNavigationType()}`}</p>;
}

function renderCallback(path: string, page: ReactElement, fragment: string) {
  render(
    <MemoryRouter
      initialEntries={['/login', `${path}${fragment}`]}
      initialIndex={1}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path={path} element={page} />
        <Route path="/new" element={<Destination />} />
        <Route path="/login" element={<Destination />} />
        <Route path="/oauth/consent" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** A signed-out visit to `path` behind sign-in, as App mounts it. */
function visitSignedOut(path: string) {
  render(
    <AuthProvider>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/login" element={<Destination />} />
          {['/oauth/consent', '/settings'].map((routePath) => (
            <Route
              key={routePath}
              path={routePath}
              element={
                <ProtectedRoute>
                  <p>signed in</p>
                </ProtectedRoute>
              }
            />
          ))}
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

const MINUTE = 60 * 1000;

const EXPIRES_AT = '2099-01-01T00:00:00+00:00';
const VALID = `#access_token=tok&token_type=Bearer&expires_at=${encodeURIComponent(EXPIRES_AT)}`;

const callbacks = [
  {
    name: 'Google',
    path: '/oauth/google/callback',
    page: <GoogleAuthCallback />,
    error: 'sign_in_failed',
  },
  {
    name: 'Magic link',
    path: '/auth/magic-link/callback',
    page: <MagicLinkCallback />,
    error: 'invalid_magic_link',
  },
];

beforeEach(async () => {
  await session.end('other_tab');
  localStorage.clear();
  sessionStorage.clear();
});

describe.each(callbacks)('the $name callback', ({ path, page, error }) => {
  it('starts the Session and replaces the callback entry with New post', async () => {
    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
    expect(session.get()).toEqual({ accessToken: 'tok', expiresAt: EXPIRES_AT });
  });

  it.each([
    ['without a fragment', ''],
    ['without a token', `#token_type=Bearer&expires_at=${encodeURIComponent(EXPIRES_AT)}`],
    ['without an expiry', '#access_token=tok&token_type=Bearer'],
    ['with an unparseable expiry', '#access_token=tok&token_type=Bearer&expires_at=soon'],
  ])('goes to the sign-in page with an error %s', async (_label, fragment) => {
    renderCallback(path, page, fragment);

    expect(await screen.findByText(`at /login?error=${error} via REPLACE`)).toBeInTheDocument();
    expect(session.get()).toBeNull();
  });
});

describe.each(callbacks)('returning after the $name callback', ({ path, page }) => {
  it('lands on the consent request the User was sent to sign in from', async () => {
    visitSignedOut('/oauth/consent?request=req_1');
    expect(await screen.findByText('at /login via REPLACE')).toBeInTheDocument();
    cleanup();

    renderCallback(path, page, VALID);

    expect(
      await screen.findByText('at /oauth/consent?request=req_1 via REPLACE'),
    ).toBeInTheDocument();
  });

  it('returns once: the next sign-in lands on New post', async () => {
    storage.set('return-to', { path: '/oauth/consent?request=req_1', savedAt: Date.now() });
    renderCallback(path, page, VALID);
    await screen.findByText('at /oauth/consent?request=req_1 via REPLACE');
    cleanup();

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });

  it('lands on New post when the request was saved over 30 minutes ago', async () => {
    storage.set('return-to', {
      path: '/oauth/consent?request=req_1',
      savedAt: Date.now() - 31 * MINUTE,
    });

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });

  it.each(['/settings', '//evil.example/oauth/consent?request=req_1', 'https://evil.example/'])(
    'never returns to %s',
    async (saved) => {
      storage.set('return-to', { path: saved, savedAt: Date.now() });

      renderCallback(path, page, VALID);

      expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
    },
  );
});

describe('a signed-out visit', () => {
  it('saves nothing to return to from a page other than the consent page', async () => {
    visitSignedOut('/settings');

    expect(await screen.findByText('at /login via REPLACE')).toBeInTheDocument();
    expect(storage.get('return-to', null)).toBeNull();
  });
});
