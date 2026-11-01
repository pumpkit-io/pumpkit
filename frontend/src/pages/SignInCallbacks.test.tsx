import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom';

vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analyticsConsent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analyticsConsent')>()),
  resetPostHog: vi.fn(),
}));
vi.mock('@/services/authService', () => ({
  authService: {
    requestMagicLink: vi.fn().mockResolvedValue({ message: 'sent' }),
    getGoogleLoginUrl: vi.fn(),
  },
}));
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
vi.mock('@/services/oauthConsentService', () => ({
  oauthConsentService: {
    get: vi.fn().mockResolvedValue({
      app: {
        name: 'Claude',
        verifiedDomain: 'claude.ai',
        redirectHost: 'claude.ai',
        isLocal: false,
      },
    }),
    approve: vi.fn().mockResolvedValue('https://claude.ai/api/mcp/auth_callback?code=abc'),
    deny: vi.fn().mockResolvedValue('https://claude.ai/api/mcp/auth_callback?error=access_denied'),
  },
}));
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn().mockResolvedValue(null) },
}));
vi.mock('@/services/billingService', () => ({
  billingService: { fetchBillingMe: vi.fn(), fetchPlans: vi.fn() },
}));

import { session } from '@/lib/session';
import { authService } from '@/services/authService';
import { storageKey } from '@/lib/storage';
import { AuthProvider } from '@/contexts/AuthContext';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { GoogleAuthCallback } from '@/components/google/GoogleAuthCallback';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { Login } from './Login';
import { MagicLinkCallback } from './MagicLinkCallback';
import { renderSignedIn } from './testing/signedInApp';

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

/** The sign-in page and the routes it leads to, opened at `initialEntry`. */
function renderSignIn(initialEntry: string, extraRoutes: ReactElement[] = []) {
  render(
    <InstanceProvider instance={SELLS_PLANS}>
      <AuthProvider>
        <MemoryRouter
          initialEntries={[initialEntry]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/login/magic-link/sent" element={<Destination />} />
            {extraRoutes}
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </InstanceProvider>,
  );
}

/** A signed-out visit to `path` behind sign-in, as App mounts it, landing on the sign-in page. */
async function visitSignedOut(path: string) {
  renderSignIn(
    path,
    ['/oauth/consent', '/settings'].map((routePath) => (
      <Route
        key={routePath}
        path={routePath}
        element={
          <ProtectedRoute>
            <p>signed in</p>
          </ProtectedRoute>
        }
      />
    )),
  );
  await screen.findByRole('heading', { name: 'Welcome back' });
}

/** Asks for a Magic link on the sign-in page already on screen. */
async function requestMagicLink() {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@example.com' } });
  fireEvent.click(screen.getByRole('button', { name: 'Email me a magic link' }));
  await screen.findByText('at /login/magic-link/sent via PUSH');
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
  // Google's page can't open in jsdom, so a click stops after it starts the sign-in.
  vi.mocked(authService.getGoogleLoginUrl).mockRejectedValue(new Error('no network'));
  await session.end('other_tab');
  localStorage.clear();
  sessionStorage.clear();
});

const storageSpies: { mockRestore: () => void }[] = [];

afterEach(() => {
  vi.useRealTimers();
  storageSpies.splice(0).forEach((spy) => spy.mockRestore());
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
    await visitSignedOut('/oauth/consent?request=req_1');
    await requestMagicLink();
    cleanup();

    renderCallback(path, page, VALID);

    expect(
      await screen.findByText('at /oauth/consent?request=req_1 via REPLACE'),
    ).toBeInTheDocument();
  });

  it('returns once: the next sign-in lands on New post', async () => {
    await visitSignedOut('/oauth/consent?request=req_1');
    cleanup();
    renderCallback(path, page, VALID);
    await screen.findByText('at /oauth/consent?request=req_1 via REPLACE');
    cleanup();

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });

  it('lands on New post when the sign-in ends over 30 minutes after the visit', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    await visitSignedOut('/oauth/consent?request=req_1');
    cleanup();
    vi.setSystemTime(Date.now() + 31 * MINUTE);

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });

  it('lands on New post after a signed-out visit to another page', async () => {
    await visitSignedOut('/settings');
    cleanup();

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });

  it.each([
    '//evil.example/oauth/consent?request=req_1',
    'https://evil.example/',
    '/oauth/consent',
  ])('never returns to a tampered saved path, %s', async (saved) => {
    localStorage.setItem(
      storageKey('return-to'),
      JSON.stringify({ path: saved, savedAt: Date.now() }),
    );

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });

  it.each(['Allow', 'Cancel'])(
    'lands on New post once the request was decided with %s',
    async (button) => {
      await visitSignedOut('/oauth/consent?request=req_1');
      cleanup();
      session.startFromFragment(VALID);
      renderSignedIn('/oauth/consent?request=req_1');
      fireEvent.click(await screen.findByRole('button', { name: button }));
      await screen.findByText(/Return to Claude\./);
      cleanup();

      renderCallback(path, page, VALID);

      expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
    },
  );

  it.each([
    ['a Magic link', requestMagicLink],
    [
      'Google',
      async () => {
        fireEvent.click(screen.getByRole('button', { name: /Google/ }));
        await screen.findByText("We couldn't start Google sign-in. Try again.");
      },
    ],
  ])('lands on New post after %s asked for on the sign-in page itself', async (_label, signIn) => {
    await visitSignedOut('/oauth/consent?request=req_1');
    cleanup();
    renderSignIn('/login');
    await signIn();
    cleanup();

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });

  it.each([
    ['SecurityError', 'The operation is insecure.'],
    ['QuotaExceededError', 'The quota has been exceeded.'],
  ])('still signs in when storage throws a %s', async (name, message) => {
    for (const method of ['getItem', 'setItem', 'removeItem'] as const) {
      const original = Storage.prototype[method];
      const spy = vi.spyOn(Storage.prototype, method).mockImplementation(function (
        this: Storage,
        key: string,
        ...rest: string[]
      ) {
        if (key === storageKey('return-to')) throw new DOMException(message, name);
        return (original as (...args: string[]) => string | null).call(this, key, ...rest);
      });
      storageSpies.push(spy);
    }

    await visitSignedOut('/oauth/consent?request=req_1');
    await requestMagicLink();
    cleanup();

    renderCallback(path, page, VALID);

    expect(await screen.findByText('at /new via REPLACE')).toBeInTheDocument();
  });
});
