import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';

vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/posthog', () => ({
  identifyUser: vi.fn(),
  resetPostHog: vi.fn(),
  capturePageview: vi.fn(),
  posthog: { capture: vi.fn(), register: vi.fn() },
}));

import { session } from '@/lib/session';
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
        <Route path="/home" element={<Destination />} />
        <Route path="/login" element={<Destination />} />
      </Routes>
    </MemoryRouter>,
  );
}

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
  it('starts the Session and replaces the callback entry with the home page', async () => {
    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /home via REPLACE')).toBeInTheDocument();
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
