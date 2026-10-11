import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { DEFAULT_INSTANCE } from '@/lib/instance';
import { Brand } from './Brand';

describe('Brand', () => {
  it('shows the app name by default', () => {
    render(
      <ThemeProvider>
        <Brand />
      </ThemeProvider>,
    );
    expect(screen.getByText('Pumpkit')).toBeInTheDocument();
  });

  it("shows the Instance's app name with its casing", () => {
    render(
      <InstanceProvider instance={{ ...DEFAULT_INSTANCE, app_name: 'acmeWriter' }}>
        <ThemeProvider>
          <Brand />
        </ThemeProvider>
      </InstanceProvider>,
    );
    expect(screen.getByText('acmeWriter')).toBeInTheDocument();
  });

  it('can hide the name', () => {
    render(
      <ThemeProvider>
        <Brand showName={false} />
      </ThemeProvider>,
    );
    expect(screen.queryByText('Pumpkit')).not.toBeInTheDocument();
  });
});
