import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_STORAGE_KEY } from '@/lib/session';
import { ErrorBoundary } from './ErrorBoundary';

function Boom(): never {
  throw new Error('Unauthorized: token expired');
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ accessToken: 't', expiresAt: 'x' }));
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('shows the generic fallback for any error and leaves the Session alone', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).not.toBeNull();
  });
});
