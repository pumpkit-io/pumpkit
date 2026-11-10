import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { LegacyLogin as Login } from './LegacyLogin';
import { authService } from '@/services/authService';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import type { Instance } from '@/lib/instance';
import { SELLS_PLANS, WITH_OPERATOR } from '@/features/instance/testInstances';

vi.mock('@/services/authService', () => ({
  authService: { requestMagicLink: vi.fn(), getGoogleLoginUrl: vi.fn() },
}));

function renderLogin(path: string, instance: Instance = SELLS_PLANS) {
  render(
    <InstanceProvider instance={instance}>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Login />
      </MemoryRouter>
    </InstanceProvider>,
  );
}

describe('the sign-in page', () => {
  it.each([
    ['invalid_magic_link', /magic link is invalid or has expired/i],
    ['account_suspended', /account has been suspended/i],
    ['sign_in_failed', /couldn't sign you in/i],
    ['x_email_required', /confirm an email address on X/i],
    ['x_authorization_invalid', /authorization expired or is invalid/i],
    ['x_authorization_cancelled', /cancelled X authorization/i],
    ['x_permissions_required', /allow all requested X permissions/i],
    ['x_provider_failed', /X is not answering/i],
    ['x_account_unavailable', /contact support/i],
    ['email_not_allowed', /^This site doesn't accept sign-ins from that email address\.$/i],
  ])('explains the %s error', (code, message) => {
    renderLogin(`/login?error=${code}`);

    expect(screen.getByRole('alert')).toHaveTextContent(message);
  });

  it('shows a different message for each error code', () => {
    const codes = [
      'invalid_magic_link',
      'account_suspended',
      'sign_in_failed',
      'email_not_allowed',
    ];
    const messages = codes.map((code) => {
      const { unmount } = render(
        <MemoryRouter
          initialEntries={[`/login?error=${code}`]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Login />
        </MemoryRouter>,
      );
      const text = screen.getByRole('alert').textContent;
      unmount();
      return text;
    });

    expect(new Set(messages).size).toBe(codes.length);
  });

  it.each([
    ['without an error code', '/login'],
    ['with an unknown error code', '/login?error=something_else'],
  ])('shows no error message %s', (_label, path) => {
    renderLogin(path);

    expect(screen.getByRole('heading', { name: 'Welcome to Pumpkit' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it("welcomes people by the Instance's app name", () => {
    renderLogin('/login', { ...SELLS_PLANS, app_name: 'acmeWriter' });

    expect(screen.getByRole('heading', { name: 'Welcome to acmeWriter' })).toBeInTheDocument();
  });

  it('tells people that continuing means agreeing to the Terms, with links to both documents', () => {
    renderLogin('/login', WITH_OPERATOR);

    const notice = screen.getByText(/^By continuing, you agree to the/);
    expect(notice).toHaveTextContent(
      'By continuing, you agree to the Terms and acknowledge the Privacy Policy.',
    );
    expect(within(notice).getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
    expect(within(notice).getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute(
      'href',
      '/privacy',
    );
  });

  it('shows no Terms notice or company footer on an Instance without Operator details', () => {
    renderLogin('/login');

    expect(screen.queryByText(/you agree to the/)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Terms' })).not.toBeInTheDocument();
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });

  it('offers Google next to the magic link when the Instance has Google sign-in', () => {
    renderLogin('/login', {
      ...SELLS_PLANS,
      sign_in_methods: ['magic_link', 'google'] as unknown as Instance['sign_in_methods'],
    });

    expect(screen.getByRole('button', { name: /google/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in with email' })).toBeInTheDocument();
  });

  it('offers only the magic link when the Instance has no Google sign-in', () => {
    renderLogin('/login', {
      ...SELLS_PLANS,
      sign_in_methods: ['magic_link'] as unknown as Instance['sign_in_methods'],
    });

    expect(screen.queryByRole('button', { name: /google/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/google/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in with email' })).toBeInTheDocument();
  });

  it('sends no magic link while the email field is empty', () => {
    renderLogin('/login');

    fireEvent.click(screen.getByRole('button', { name: 'Sign in with email' }));

    expect(authService.requestMagicLink).not.toHaveBeenCalled();
  });

  it('says the site does not accept an email the Sign-up allowlist refuses', async () => {
    vi.mocked(authService.requestMagicLink).mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'email_not_allowed' } },
    });
    renderLogin('/login');

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'mallory@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with email' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /^This site doesn't accept sign-ins from that email address\.$/i,
    );
  });
});
