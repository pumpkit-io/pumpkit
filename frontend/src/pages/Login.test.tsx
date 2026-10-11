import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Login } from './Login';
import { authService } from '@/services/authService';

vi.mock('@/services/authService', () => ({
  authService: { requestMagicLink: vi.fn(), getGoogleLoginUrl: vi.fn() },
}));

function renderLogin(path: string) {
  render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Login />
    </MemoryRouter>,
  );
}

describe('the sign-in page', () => {
  it.each([
    ['invalid_magic_link', /magic link is invalid or has expired/i],
    ['account_suspended', /account has been suspended/i],
    ['sign_in_failed', /couldn't sign you in/i],
    ['email_not_allowed', /doesn't accept sign-ins from that email/i],
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

    expect(screen.getByText('Welcome back')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('tells people that continuing means agreeing to the Terms, with links to both documents', () => {
    renderLogin('/login');

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

  it('says the Instance does not accept an email the Sign-up allowlist refuses', async () => {
    vi.mocked(authService.requestMagicLink).mockRejectedValueOnce({
      response: { status: 403, data: { detail: 'email_not_allowed' } },
    });
    renderLogin('/login');

    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'mallory@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Email me a magic link' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /doesn't accept sign-ins from that email/i,
    );
  });
});
