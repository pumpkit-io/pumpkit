import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
  oauthConsentService: { get: vi.fn(), approve: vi.fn(), deny: vi.fn() },
}));
vi.mock('@/services/onboardingService', () => ({
  onboardingService: { fetchNextStep: vi.fn() },
}));
vi.mock('@/services/billingService', () => ({
  billingService: { fetchBillingMe: vi.fn(), fetchPlans: vi.fn() },
}));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { session } from '@/lib/session';
import { oauthConsentService, type ConsentApp } from '@/services/oauthConsentService';
import { onboardingService } from '@/services/onboardingService';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { MagicLinkCallback } from './MagicLinkCallback';
import { apiError, currentPath, renderSignedIn } from './testing/signedInApp';

const CLAUDE: ConsentApp = {
  name: 'Claude',
  verifiedDomain: 'claude.ai',
  redirectHost: 'claude.ai',
  isLocal: false,
};
const CLAUDE_CODE: ConsentApp = {
  name: 'Claude Code',
  verifiedDomain: 'claude.ai',
  redirectHost: null,
  isLocal: true,
};
const CURSOR: ConsentApp = {
  name: 'Cursor',
  verifiedDomain: null,
  redirectHost: null,
  isLocal: true,
};

const APPROVED_URL =
  'http://127.0.0.1:33418/callback?code=abc&state=xyz&iss=http%3A%2F%2Flocalhost';
const DENIED_URL = 'http://127.0.0.1:33418/callback?error=access_denied&state=xyz';
const NETWORK_ERROR = Object.assign(new Error('Network Error'), { isAxiosError: true });

function pendingWith(app: ConsentApp) {
  vi.mocked(oauthConsentService.get).mockResolvedValue({ app });
}

function renderConsent(query = '?request=req_1', nextStep: 'paywall' | 'persona' | null = null) {
  return renderSignedIn(`/oauth/consent${query}`, { nextStep });
}

const EXPIRES_AT = encodeURIComponent('2099-01-01T00:00:00+00:00');

/** Opens a valid Magic link's callback; the consent route shows where it landed. */
function signInWithMagicLink() {
  render(
    <InstanceProvider instance={SELLS_PLANS}>
      <MemoryRouter
        initialEntries={[
          `/auth/magic-link/callback#access_token=tok&token_type=Bearer&expires_at=${EXPIRES_AT}`,
        ]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/auth/magic-link/callback" element={<MagicLinkCallback />} />
          <Route path="/new" element={<Landing />} />
          <Route path="/oauth/consent" element={<Landing />} />
        </Routes>
      </MemoryRouter>
    </InstanceProvider>,
  );
}

function Landing() {
  const { pathname, search } = useLocation();
  return <p>{`at ${pathname}${search}`}</p>;
}

async function page() {
  return within(await screen.findByRole('main'));
}

const buttons = () => ({
  allow: screen.queryByRole('button', { name: 'Allow' }),
  cancel: screen.queryByRole('button', { name: 'Cancel' }),
});

/** A promise and the function that settles it, to hold a request in flight. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe('Consent page', () => {
  beforeEach(() => {
    vi.mocked(oauthConsentService.get).mockReset();
    vi.mocked(oauthConsentService.approve).mockReset().mockResolvedValue(APPROVED_URL);
    vi.mocked(oauthConsentService.deny).mockReset().mockResolvedValue(DENIED_URL);
    vi.mocked(onboardingService.fetchNextStep).mockReset().mockResolvedValue(null);
    vi.mocked(redirectTo).mockReset();
    vi.mocked(track).mockReset();
    localStorage.clear();
  });

  describe('Invalid link', () => {
    it.each([
      ['invalid_client', "The app isn't registered with Pumpkit."],
      ['invalid_redirect_uri', "The return address doesn't match what the app registered."],
    ])('explains %s and offers no buttons', async (code, cause) => {
      renderConsent(`?error=${code}`);
      const main = await page();

      expect(
        main.getByRole('heading', { name: "This connection request isn't valid" }),
      ).toBeInTheDocument();
      expect(main.getByText(cause)).toBeInTheDocument();
      expect(main.getByText('Try connecting again from the app.')).toBeInTheDocument();
      expect(buttons()).toEqual({ allow: null, cancel: null });
      expect(oauthConsentService.get).not.toHaveBeenCalled();
    });

    it('treats a link with no request as invalid', async () => {
      renderConsent('');
      const main = await page();

      expect(
        main.getByRole('heading', { name: "This connection request isn't valid" }),
      ).toBeInTheDocument();
      expect(buttons()).toEqual({ allow: null, cancel: null });
    });
  });

  it('shows a skeleton and no buttons while the request loads', async () => {
    vi.mocked(oauthConsentService.get).mockReturnValue(new Promise(() => {}));
    renderConsent();

    expect(
      await screen.findByRole('status', { name: 'Loading the connection request' }),
    ).toBeInTheDocument();
    expect(buttons()).toEqual({ allow: null, cancel: null });
  });

  it('says only that an expired or used request has to start again from the app', async () => {
    vi.mocked(oauthConsentService.get).mockRejectedValue(apiError(404, 'Not found'));
    renderConsent();
    const main = await page();

    expect(
      await main.findByText(
        'This request expired or was already used. Start connecting again from your app.',
      ),
    ).toBeInTheDocument();
    expect(main.queryByRole('heading')).not.toBeInTheDocument();
    expect(main.queryAllByRole('button')).toEqual([]);
  });

  it('says when the request could not load, and tries again', async () => {
    vi.mocked(oauthConsentService.get).mockRejectedValueOnce(NETWORK_ERROR);
    pendingWith(CLAUDE);
    renderConsent();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("Couldn't load this connection request.");
    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));

    expect(
      await screen.findByRole('heading', { name: 'Connect Claude to Pumpkit' }),
    ).toBeInTheDocument();
    expect(oauthConsentService.get).toHaveBeenCalledTimes(2);
  });

  describe('Ready', () => {
    it('names the app, the account, what it can do and where it sends the User back', async () => {
      pendingWith(CLAUDE);
      renderConsent();
      const main = await page();

      expect(
        await main.findByRole('heading', { name: 'Connect Claude to Pumpkit' }),
      ).toBeInTheDocument();
      expect(await main.findByText(/Signed in as/)).toHaveTextContent(
        'Signed in as ada@example.com',
      );
      expect(
        main.getByText(
          "Claude will be able to use Pumpkit as you: write and revise posts, manage your inspiration authors, schedule posts and publish them on X. It can't see your password or change your subscription.",
        ),
      ).toBeInTheDocument();
      expect(main.getByText('Verified: claude.ai')).toBeInTheDocument();
      expect(main.getByText('Sends you back to claude.ai')).toBeInTheDocument();
      expect(
        main.getByText('Only allow apps you trust. You can disconnect it anytime in Settings.'),
      ).toBeInTheDocument();
      expect(buttons().allow).toBeEnabled();
      expect(buttons().cancel).toBeEnabled();
      expect(oauthConsentService.get).toHaveBeenCalledWith('req_1');
      expect(track).toHaveBeenCalledWith('oauth_consent_viewed', { verified: true, local: false });
    });

    it('says a verified app on this computer has no site to send the User back to', async () => {
      pendingWith(CLAUDE_CODE);
      renderConsent();
      const main = await page();

      expect(await main.findByText('Verified: claude.ai')).toBeInTheDocument();
      expect(main.getByText('An app on this computer')).toBeInTheDocument();
      expect(main.queryByText(/Sends you back/)).not.toBeInTheDocument();
    });

    it('warns about an unverified app on this computer and still allows it in one click', async () => {
      pendingWith(CURSOR);
      renderConsent();
      const main = await page();

      expect(await main.findByText('Unverified app')).toBeInTheDocument();
      expect(main.getByText('An app on this computer')).toBeInTheDocument();
      fireEvent.click(main.getByRole('button', { name: 'Allow' }));

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith(APPROVED_URL));
    });

    it('renders for a User who has not finished Onboarding', async () => {
      vi.mocked(onboardingService.fetchNextStep).mockResolvedValue('persona');
      pendingWith(CLAUDE);
      renderConsent('?request=req_1', 'persona');

      expect(
        await screen.findByRole('heading', { name: 'Connect Claude to Pumpkit' }),
      ).toBeInTheDocument();
      expect(currentPath()).toBe('/oauth/consent');
    });

    it('signs out from "Not you?" and comes back to the same request after sign-in', async () => {
      const end = vi.spyOn(session, 'end').mockResolvedValue();
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Not you?' }));

      await waitFor(() => expect(end).toHaveBeenCalledWith('user'));
      end.mockRestore();
      cleanup();
      signInWithMagicLink();

      expect(await screen.findByText('at /oauth/consent?request=req_1')).toBeInTheDocument();
    });
  });

  describe('Allow', () => {
    it('sends the browser to the app with the code, then says to return to it', async () => {
      pendingWith(CURSOR);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      expect(await screen.findByText('Done. Return to Cursor.')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Go to Pumpkit' })).toHaveAttribute('href', '/new');
      expect(oauthConsentService.approve).toHaveBeenCalledWith('req_1');
      expect(redirectTo).toHaveBeenCalledWith(APPROVED_URL);
      expect(buttons()).toEqual({ allow: null, cancel: null });
      expect(track).toHaveBeenCalledWith('oauth_consent_approved', {
        verified: false,
        local: true,
      });
    });

    it('disables both buttons while the answer is on its way', async () => {
      const answer = deferred<string>();
      vi.mocked(oauthConsentService.approve).mockReturnValue(answer.promise);
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      await waitFor(() => expect(buttons().allow).toBeDisabled());
      expect(buttons().cancel).toBeDisabled();
      fireEvent.click(buttons().allow!);
      expect(oauthConsentService.approve).toHaveBeenCalledTimes(1);
      answer.resolve(APPROVED_URL);
      expect(await screen.findByText('Done. Return to Claude.')).toBeInTheDocument();
    });

    it('offers to subscribe in place of the buttons when the User has no Subscription', async () => {
      vi.mocked(oauthConsentService.approve).mockRejectedValue(
        apiError(403, 'This needs a subscription. Subscribe to continue.'),
      );
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      expect(
        await screen.findByText('Connecting an app needs a subscription.'),
      ).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Subscribe' })).toHaveAttribute('href', '/subscribe');
      expect(buttons()).toEqual({ allow: null, cancel: null });
      expect(redirectTo).not.toHaveBeenCalled();
    });

    it('shows any other refusal as an error and keeps the buttons', async () => {
      vi.mocked(oauthConsentService.approve).mockRejectedValue(
        apiError(403, "Your account can't connect apps."),
      );
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        "Your account can't connect apps.",
      );
      expect(screen.queryByRole('link', { name: 'Subscribe' })).not.toBeInTheDocument();
      expect(buttons().allow).toBeEnabled();
    });

    it.each([
      'https://claude.ai/api/mcp/auth_callback?code=abc',
      'http://localhost:33418/callback?code=abc',
      'http://127.0.0.1:33418/callback?code=abc',
      'http://[::1]:33418/callback?code=abc',
      'cursor://anysphere.cursor-mcp/oauth/callback?code=abc',
    ])('opens the return address %s', async (url) => {
      vi.mocked(oauthConsentService.approve).mockResolvedValue(url);
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith(url));
    });

    it.each([
      'http://claude.ai/callback?code=abc',
      'javascript:alert(1)',
      'JavaScript:alert(1)',
      'data:text/html,hi',
      'vbscript:msgbox(1)',
      'file:///etc/passwd',
      'not a url',
    ])('refuses to open the return address %s', async (url) => {
      vi.mocked(oauthConsentService.approve).mockResolvedValue(url);
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        "Claude gave a return address Pumpkit won't open. Try connecting again from the app.",
      );
      expect(redirectTo).not.toHaveBeenCalled();
      expect(buttons()).toEqual({ allow: null, cancel: null });
    });

    it('says what failed on a network error and keeps the buttons to try again', async () => {
      vi.mocked(oauthConsentService.approve).mockRejectedValueOnce(NETWORK_ERROR);
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      const alert = await screen.findByRole('alert');
      expect(alert).toHaveTextContent(
        "Couldn't connect Claude. Check your connection and try again.",
      );
      expect(buttons().allow).toBeEnabled();
      expect(buttons().cancel).toBeEnabled();
      fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith(APPROVED_URL));
    });

    it('says the request expired when it ended before the User allowed it', async () => {
      vi.mocked(oauthConsentService.approve).mockRejectedValue(apiError(404, 'Not found'));
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));

      expect(
        await screen.findByText(
          'This request expired or was already used. Start connecting again from your app.',
        ),
      ).toBeInTheDocument();
      expect(within(screen.getByRole('main')).queryByRole('heading')).not.toBeInTheDocument();
      expect(buttons()).toEqual({ allow: null, cancel: null });
    });
  });

  describe('Cancel', () => {
    it('tells the app the User refused', async () => {
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith(DENIED_URL));
      expect(oauthConsentService.deny).toHaveBeenCalledWith('req_1');
      expect(oauthConsentService.approve).not.toHaveBeenCalled();
      expect(await screen.findByText('Cancelled. Return to Claude.')).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('oauth_consent_denied', { verified: true, local: false });
    });

    it('says what failed on a network error and keeps the buttons', async () => {
      vi.mocked(oauthConsentService.deny).mockRejectedValueOnce(NETWORK_ERROR);
      pendingWith(CLAUDE);
      renderConsent();

      fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        "Couldn't cancel. Check your connection and try again.",
      );
      expect(buttons().cancel).toBeEnabled();
    });
  });
});
