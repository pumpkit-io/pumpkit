import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TokenErrorBoundary } from './TokenErrorBoundary';

const SESSION_KEY = 'pumpkit:session';

function Boom(): never {
  throw new Error('Unauthorized: token expired');
}

describe('TokenErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    localStorage.setItem(SESSION_KEY, JSON.stringify({ accessToken: 't', expiresAt: 'x' }));
  });
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('shows the generic fallback for any error and leaves the Session alone', () => {
    render(
      <TokenErrorBoundary>
        <Boom />
      </TokenErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(localStorage.getItem(SESSION_KEY)).not.toBeNull();
  });
});
