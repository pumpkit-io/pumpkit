import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Login } from './Login';

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
  ])('explains the %s error', (code, message) => {
    renderLogin(`/login?error=${code}`);

    expect(screen.getByRole('alert')).toHaveTextContent(message);
  });

  it('shows a different message for each error code', () => {
    const messages = ['invalid_magic_link', 'account_suspended', 'sign_in_failed'].map((code) => {
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

    expect(new Set(messages).size).toBe(3);
  });

  it.each([
    ['without an error code', '/login'],
    ['with an unknown error code', '/login?error=something_else'],
  ])('shows no error message %s', (_label, path) => {
    renderLogin(path);

    expect(screen.getByText('Welcome back')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
