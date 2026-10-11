import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { WITH_OPERATOR } from '@/features/instance/testInstances';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { DEFAULT_INSTANCE, type Instance } from '@/lib/instance';
import { MagicLinkSent } from './MagicLinkSent';

function renderSent(instance: Instance) {
  render(
    <InstanceProvider instance={instance}>
      <ThemeProvider>
        <MemoryRouter
          initialEntries={[
            { pathname: '/login/magic-link/sent', state: { email: 'a@example.com' } },
          ]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <MagicLinkSent />
        </MemoryRouter>
      </ThemeProvider>
    </InstanceProvider>,
  );
}

describe('the Magic link sent page', () => {
  it("offers to contact the Instance's support address", () => {
    renderSent(WITH_OPERATOR);

    expect(screen.getByRole('link', { name: 'Contact support' })).toHaveAttribute(
      'href',
      expect.stringMatching(/\/support\/contact$/),
    );
  });

  it('offers no support contact on an Instance without Operator details', () => {
    renderSent(DEFAULT_INSTANCE);

    expect(screen.getByText(/Check your spam folder/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Contact support' })).not.toBeInTheDocument();
  });
});
